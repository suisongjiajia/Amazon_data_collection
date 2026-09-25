"""
listing 套图：通义 VL 读图出提示词 → qwen-image 作图。

套图结构：
- 每色 1 张主图（Ozon 海报风，允许俄语卖点字，禁止中文）
- 共用：2 场景 + 2 细节 + 1 结构尺寸

用法:
  .\\.python\\python.exe backend\\scripts\\generate_listing_suite.py --edit-id 108
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    key, value = key.strip(), value.strip().strip('"').strip("'")
    if key and key not in os.environ:
        os.environ[key] = value

from db.ozon_workflow import get_product_edit, update_product_edit, update_product_edit_variant  # noqa: E402
from db.serialization import fetch_one  # noqa: E402
from integrations.aliyun_oss import rehost_image_urls  # noqa: E402
from integrations.qwen_image import QwenImageClient, QwenImageError  # noqa: E402
from integrations.qwen_vl import QwenVLClient, QwenVLError  # noqa: E402

ROLES = ("main", "scene_1", "scene_2", "detail_1", "detail_2", "structure")

VL_SYSTEM = """你是 Ozon 跨境电商视觉导演。根据商品参考图，为图像生成模型撰写英文作图提示词（img2img）。
必须输出 JSON 对象，键为：main, scene_1, scene_2, detail_1, detail_2, structure，值均为字符串提示词。
要求：
1) main：Ozon 主图海报风——产品大、可带生活场景虚化背景、俄语大标题与卖点图标/角标（如 УЮТНОЕ МЕСТО、для кошек и собак、保暖/可拆卸的俄语表达），高对比专业电商卡。
2) scene_1 / scene_2：真实家居场景，宠物正在使用产品，自然光，构图不同。
3) detail_1 / detail_2：材质与做工微距（绒毛、绗缝、拉链/可拆卸等）。
4) structure：正视+侧视结构尺寸图，可用俄语尺寸标注或 cm 数字箭头，干净信息图。
5) 所有提示词必须强调：禁止任何中文/汉字出现在成图中；不要从参考图复制中文；保持参考图中的产品外形、颜色、花纹一致。
6) 提示词用英文写（俄语文案内容可以写在英文提示里用引号给出要渲染的俄语句子）。
7) 只输出 JSON，不要 markdown。"""


def _load_json(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _color_label(variant: dict[str, Any]) -> str:
    va = _load_json(variant.get("variant_attributes") or {}) or {}
    for key in ("颜色", "款式", "Цвет", "区分项"):
        text = str(va.get(key) or "").strip()
        if text:
            return text.split(" · ")[0].strip() or text
    return str(variant.get("sku") or "variant")


def _color_en(label: str) -> str:
    text = str(label or "")
    for needle, en in (
        ("绿", "green gingham"),
        ("蓝", "blue gingham"),
        ("灰", "gray"),
        ("粉", "pink"),
        ("棕", "brown"),
        ("米", "beige"),
    ):
        if needle in text:
            return en
    return "same color/pattern as reference"


def _raw_main(variant: dict[str, Any]) -> str:
    rid = variant.get("raw_product_variant_id")
    if rid:
        row = fetch_one("SELECT main_image_url FROM raw_product_variant WHERE id=%s", (int(rid),))
        if row and row.get("main_image_url"):
            return str(row["main_image_url"]).strip()
    return str(variant.get("image_url") or "").strip()


def _family_gallery(family_id: int) -> list[str]:
    row = fetch_one(
        "SELECT main_image_url, bullet_points, raw_payload FROM raw_product_family WHERE id=%s",
        (family_id,),
    )
    if not row:
        return []
    out: list[str] = []
    main = str(row.get("main_image_url") or "").strip()
    if main:
        out.append(main)
    bp = _load_json(row.get("bullet_points") or [])
    if isinstance(bp, list):
        for url in bp:
            text = str(url or "").strip()
            if text.startswith("http") and text not in out:
                out.append(text)
    raw = _load_json(row.get("raw_payload") or {})
    if isinstance(raw, dict):
        for url in raw.get("images") or []:
            text = str(url or "").strip()
            if text.startswith("http") and text not in out:
                out.append(text)
    return out


def _vl_prompts(
    vl: QwenVLClient,
    *,
    image_url: str,
    title: str,
    color_en: str,
    size_hint: str,
) -> dict[str, str]:
    user = (
        f"Russian listing title (for context only, DeepSeek handles copy elsewhere): {title}\n"
        f"Colorway in English: {color_en}\n"
        f"Approximate size hint: {size_hint}\n"
        "Look at the product image and write img2img prompts for roles "
        "main, scene_1, scene_2, detail_1, detail_2, structure as specified."
    )
    data = vl.chat_vision_json(
        image_url=image_url,
        system_prompt=VL_SYSTEM,
        prompt=user,
        temperature=0.35,
    )
    out: dict[str, str] = {}
    for role in ROLES:
        text = str(data.get(role) or "").strip()
        if text:
            # 再钉死一次禁中文
            if "Chinese" not in text and "chinese" not in text:
                text += " Absolutely no Chinese characters in the final image."
            out[role] = text
    missing = [r for r in ROLES if r not in out]
    if missing:
        raise QwenVLError(f"VL 缺少角色提示词: {missing}")
    return out


def _generate_image(
    client: QwenImageClient,
    *,
    prompt: str,
    image_url: str,
    label: str,
) -> str | None:
    print(f"\n[image:{label}] ...")
    t0 = time.time()
    # 过长提示词易触发作图 API InvalidParameter
    text = str(prompt or "").strip()
    if len(text) > 1200:
        text = text[:1200].rstrip() + " No Chinese characters in the final image."
    neg = (
        "chinese characters, hanzi, CJK text, chinese watermark, "
        "garbled letters, low quality, deformed product, wrong pattern"
    )
    try:
        result = client.generate(
            text,
            image_url=image_url,
            prompt_extend=False,
            negative_prompt=neg,
        )
    except QwenImageError as exc:
        print(f"  FAIL: {exc}")
        return None
    out = (result.get("images") or [None])[0]
    print(f"  ok {time.time() - t0:.1f}s -> {out}")
    return str(out) if out else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edit-id", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-rehost", action="store_true")
    parser.add_argument("--dump-prompts", default="", help="把 VL 提示词写到 JSON 文件")
    args = parser.parse_args()

    edit = get_product_edit(args.edit_id)
    title = str(edit.get("title") or "").strip()
    variants = list(edit.get("variants") or [])
    family_id = int(edit["raw_product_family_id"])
    gallery = _family_gallery(family_id)
    size_hint = "40 x 36 x 20 cm"

    groups: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        main = _raw_main(variant)
        if main:
            groups.setdefault(main, []).append(variant)

    print(f"edit={args.edit_id} title={title[:70]}")
    print(f"color_groups={len(groups)} gallery={len(gallery)}")
    if not groups:
        print("无变体主图")
        return 1

    shared_ref = next(iter(groups.keys()))
    if len(gallery) > 2:
        shared_ref_detail = gallery[min(3, len(gallery) - 1)]
    else:
        shared_ref_detail = shared_ref

    vl = QwenVLClient()
    img = QwenImageClient()

    # 共用副图提示词：用第一色主图读一次
    first_members = next(iter(groups.values()))
    first_color_en = _color_en(_color_label(first_members[0]))
    print(f"\n[vl] reading shared ref for prompts color={first_color_en}")
    shared_prompts = _vl_prompts(
        vl,
        image_url=shared_ref,
        title=title,
        color_en=first_color_en,
        size_hint=size_hint,
    )
    print("  roles:", ", ".join(shared_prompts.keys()))

    # 每色主图单独再让 VL 出 main（颜色不同）
    main_prompts: dict[str, str] = {}
    for raw_main, members in groups.items():
        color_en = _color_en(_color_label(members[0]))
        print(f"[vl] main prompt for {color_en}")
        try:
            one = _vl_prompts(
                vl,
                image_url=raw_main,
                title=title,
                color_en=color_en,
                size_hint=size_hint,
            )
            main_prompts[raw_main] = one["main"]
        except QwenVLError as exc:
            print(f"  VL fail, fallback shared main: {exc}")
            main_prompts[raw_main] = shared_prompts["main"] + f" Colorway: {color_en}."

    if args.dump_prompts:
        Path(args.dump_prompts).write_text(
            json.dumps(
                {"shared": shared_prompts, "mains": {k[-40:]: v for k, v in main_prompts.items()}},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"prompts -> {args.dump_prompts}")

    if args.dry_run:
        return 0

    # 作图：共用副图
    shared_jobs = [
        ("scene_1", shared_prompts["scene_1"], shared_ref),
        ("scene_2", shared_prompts["scene_2"], shared_ref),
        ("detail_1", shared_prompts["detail_1"], shared_ref_detail),
        ("detail_2", shared_prompts["detail_2"], shared_ref_detail),
        ("structure", shared_prompts["structure"], shared_ref),
    ]
    shared_urls: list[str] = []
    for role, prompt, ref in shared_jobs:
        url = _generate_image(img, prompt=prompt, image_url=ref, label=role)
        if url:
            shared_urls.append(url)

    main_map: dict[str, str] = {}
    for raw_main, prompt in main_prompts.items():
        color_en = _color_en(_color_label(groups[raw_main][0]))
        url = _generate_image(img, prompt=prompt, image_url=raw_main, label=f"main:{color_en}")
        if url:
            main_map[raw_main] = url

    if not main_map and not shared_urls:
        print("全部生成失败")
        return 1

    all_new = list(dict.fromkeys([*main_map.values(), *shared_urls]))
    remap: dict[str, str] = {}
    if not args.skip_rehost and all_new:
        print(f"\nrehost {len(all_new)} -> OSS")
        try:
            hosted = rehost_image_urls(all_new, sku=f"edit-{args.edit_id}-vl")
            for src, dst in zip(all_new, hosted.get("images") or []):
                if dst:
                    remap[src] = dst
            failed = [u for u in all_new if u not in remap]
            if failed:
                time.sleep(2)
                hosted2 = rehost_image_urls(failed, sku=f"edit-{args.edit_id}-vl2")
                for src, dst in zip(failed, hosted2.get("images") or []):
                    if dst:
                        remap[src] = dst
            print(f"  rehosted={len(remap)}")
        except Exception as exc:
            print(f"  rehost failed: {exc}")

    def fin(url: str) -> str:
        return remap.get(url, url)

    shared_final = [fin(u) for u in shared_urls]
    product_images: list[str] = []
    if main_map:
        product_images.append(fin(next(iter(main_map.values()))))
    for u in shared_final:
        if u not in product_images:
            product_images.append(u)

    print("\nwrite DB")
    update_product_edit(args.edit_id, images=product_images[:15])
    for raw_main, members in groups.items():
        new_main = fin(main_map[raw_main]) if raw_main in main_map else None
        for variant in members:
            gallery_out: list[str] = []
            if new_main:
                gallery_out.append(new_main)
            for u in shared_final:
                if u not in gallery_out:
                    gallery_out.append(u)
            va = dict(_load_json(variant.get("variant_attributes") or {}) or {})
            va["images"] = gallery_out[:15]
            if gallery_out:
                va["image_url"] = gallery_out[0]
            update_product_edit_variant(
                int(variant["id"]),
                image_url=gallery_out[0] if gallery_out else None,
                variant_attributes=va,
            )
            print(f"  variant {variant['id']} {_color_label(variant)[:24]} imgs={len(gallery_out)}")

    print("DONE")
    print(f"mains={len(main_map)} shared={len(shared_final)} (VL→qwen-image)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

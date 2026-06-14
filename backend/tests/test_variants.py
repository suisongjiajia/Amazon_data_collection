from bs4 import BeautifulSoup

from collector.variant_parser import parse_variants


def test_parse_variants_from_json() -> None:
    html = """
    "dimensionToAsinMap" : {"0_0":"B0DJ3NTXJT","1_0":"B0FC25W1BT"},
    "variationValues" : {"size_name":["Small","Large"],"color_name":["Black"]},
    "dimensionValuesDisplayData" : {
        "B0DJ3NTXJT":["Small","Black"],
        "B0FC25W1BT":["Large","Black"]
    },
    "variationDisplayLabels" : {"size_name":"Size","color_name":"Color"},
    """
    doc = BeautifulSoup("<html></html>", "html.parser")
    variants = parse_variants(html, doc, "B0FC25W1BT")

    assert len(variants) == 2
    assert variants[0].attributes == {"Size": "Small", "Color": "Black"}
    assert variants[1].attributes == {"Size": "Large", "Color": "Black"}


def test_parse_variants_from_dom_for_custom_dimension() -> None:
    html = "<html></html>"
    html_doc = """
    <div id="inline-twister-row-style_name">
      <span class="a-form-label">Style:</span>
      <li data-asin="B0TEST1234"><span class="swatch-title-text-display">Classic</span></li>
      <li data-asin="B0TEST5678"><span class="swatch-title-text-display">Modern</span></li>
    </div>
    """
    doc = BeautifulSoup(html_doc, "html.parser")
    variants = parse_variants(html, doc, "B0TEST1234")

    assert len(variants) == 2
    assert variants[0].attributes["Style"] == "Classic"
    assert variants[1].attributes["Style"] == "Modern"

from bs4 import BeautifulSoup

from collector.collector import AmazonCollector


def test_extract_asins_skips_sponsored_and_scopes_to_main_slot() -> None:
    html = """
    <html>
      <body>
        <div data-asin="BADASIN000" data-component-type="sp-sponsored-result"></div>
        <div class="s-main-slot">
          <div data-component-type="s-search-result" data-asin="B0BRKPBMVY"></div>
          <div data-component-type="sp-sponsored-result">
            <div data-asin="SPONSORED00"></div>
          </div>
          <div data-component-type="s-search-result" data-asin="B0BBBBBBBB"></div>
        </div>
        <div data-asin="OUTSIDEMAI"></div>
      </body>
    </html>
    """
    collector = AmazonCollector()
    asins = collector._extract_asins_from_listing(BeautifulSoup(html, "html.parser"))
    assert asins == ["B0BRKPBMVY", "B0BBBBBBBB"]

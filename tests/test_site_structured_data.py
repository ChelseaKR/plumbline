"""The machine-readable claim and the human-readable one are the same claim.

`site/index.html` states what it is twice: once in tags a person's browser
renders, and once in a schema.org graph only a crawler reads. The second is
the half nobody looks at, which makes it the half that rots -- a title changed
in the template and not in the node publishes two different answers to "what
is this page", and the wrong one is the one a search result shows.

So none of these tests assert a literal. Each one reads a value out of the
graph and holds it against the tag, the file or the packaging metadata the
value is supposed to have come from. A node that stopped being *derived* fails
here even if it still says something plausible, which is the only failure
worth catching: a node that is merely wrong is rare, and a node that is
quietly stale is the normal outcome.

Nothing in this file imports `tools/build_site.py`. `tests/test_site.py`
already proves the committed page is byte-for-byte what the generator
produces, so this reads the committed page and nothing else: asking the
generator what the answer is cannot catch a generator that fabricates, which
is the same argument `plumbline verify` makes about a report vouching for its
own seal.

The standard library only, like the rest of the suite -- `html.parser`,
`json`, `tomllib`, `re`. The harness has no third-party dependencies and
neither does anything that checks it.
"""

from __future__ import annotations

import json
import re
import tomllib
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SITE_DIR = REPO / "site"
PAGE = SITE_DIR / "index.html"

# Which published pages carry the graph, decided by name rather than by
# whatever is under `site/` (owner decision 2026-09-18). The home page is the
# page that says what this project is, so it is the one that says it to a
# crawler. `privacy.html` says what the site collects about a visitor, which
# is not a claim about the project, so it carries no graph. Every page under
# `site/` has to be in exactly one of the two, so a page added later is a
# decision somebody makes rather than a page no test reads.
GRAPH_PAGES = (PAGE,)
WITHOUT_A_GRAPH = {
    SITE_DIR / "privacy.html": "says what the site collects, not what it is",
}
PROJECT = REPO / "pyproject.toml"
CITATION = REPO / "CITATION.cff"

# The one value in the node that schema.org will not take as a bare string.
# Restated here rather than imported, for the reason in the module docstring:
# a check that reads the generator's own constant back out of the generator
# proves the generator is self-consistent, which it always is.
SPDX_LICENSE_PAGE = "https://spdx.org/licenses/{}.html"


class Head(HTMLParser):
    """What the head declares, taken from the elements rather than the text.

    Matching on a string is the failure this file is written to avoid at one
    remove. `"application/ld+json" in page` is true of a page that mentions
    the media type in a comment and of a page that names it in an attribute
    nobody reads, and false of a real block written `type = 'application/ld+json'`
    with spaces around the equals sign. So this matches on the element and its
    `type` attribute, and on nothing else.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.title = ""
        self.canonical = ""
        self.meta: dict[str, str] = {}
        self.ld_blocks: list[str] = []
        self.scripts: list[dict[str, str]] = []
        self._in_title = False
        self._in_ld = False
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        at = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = at.get("lang", "")
        elif tag == "title":
            self._in_title = True
            self._buffer = []
        elif tag == "meta":
            key = at.get("name") or at.get("property")
            if key:
                self.meta[key] = at.get("content", "")
        elif tag == "link" and at.get("rel") == "canonical":
            self.canonical = at.get("href", "")
        elif tag == "script":
            self.scripts.append(at)
            if at.get("type", "").strip() == "application/ld+json":
                self._in_ld = True
                self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self.title = "".join(self._buffer)
            self._in_title = False
        elif tag == "script" and self._in_ld:
            self.ld_blocks.append("".join(self._buffer))
            self._in_ld = False

    def handle_data(self, data: str) -> None:
        if self._in_title or self._in_ld:
            self._buffer.append(data)


class TheStructuredDataIsDerived(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # The examinable set is every HTML file `.github/workflows/pages.yml`
        # uploads, which is `path: site`. A page added under `site/` is
        # covered by the script and harvest checks below without anyone
        # remembering to add it, and fails the classification check until
        # somebody decides whether it carries a graph.
        cls.pages = sorted(SITE_DIR.rglob("*.html"))
        cls.graph_pages = [page for page in cls.pages if page in GRAPH_PAGES]
        cls.parsed: dict[Path, Head] = {}
        for page in cls.pages:
            head = Head()
            head.feed(page.read_text(encoding="utf-8"))
            head.close()
            cls.parsed[page] = head
        cls.project = tomllib.loads(
            PROJECT.read_text(encoding="utf-8"))["project"]
        reports = sorted((REPO / "audits").glob("*/report.json"))
        cls.report = json.loads(reports[0].read_text(encoding="utf-8"))

    def graph(self, page: Path) -> dict[str, dict]:
        """Every node of a page's single JSON-LD block, keyed by `@id`."""
        blocks = self.parsed[page].ld_blocks
        self.assertEqual(
            len(blocks), 1,
            f"{page.name} carries {len(blocks)} ld+json blocks, expected 1")
        payload = json.loads(blocks[0])
        self.assertEqual(payload.get("@context"), "https://schema.org")
        nodes = payload.get("@graph")
        self.assertIsInstance(nodes, list)
        by_id = {node["@id"]: node for node in nodes}
        self.assertEqual(len(by_id), len(nodes), "two nodes share one @id")
        return by_id

    def node(self, page: Path, type_: str) -> dict:
        found = [n for n in self.graph(page).values() if n["@type"] == type_]
        self.assertEqual(len(found), 1, f"{page.name}: {len(found)} {type_}")
        return found[0]

    # --- the examinable set -------------------------------------------------

    def test_there_is_a_page_to_examine(self):
        # Without this every other test in the class passes having read
        # nothing, which is the vacuous pass this repository exists to refuse:
        # a `for` loop over an empty list is green and proves exactly as much
        # as not running.
        self.assertNotEqual(list(self.pages), [],
                            "site/ holds no HTML to examine")

    def test_every_published_page_is_classified(self):
        # Every page is either one that carries the graph or one named, with
        # its reason, as carrying none. A page in neither list is a page this
        # module would otherwise skip without saying so.
        self.assertEqual(
            set(self.pages), set(GRAPH_PAGES) | set(WITHOUT_A_GRAPH),
            "a page under site/ is neither described nor exempted by name")
        self.assertFalse(set(GRAPH_PAGES) & set(WITHOUT_A_GRAPH))

    def test_every_graph_page_carries_a_node(self):
        # The defect this gate is for. An absent node is invisible in a
        # browser, so nothing else in this repository would ever notice.
        self.assertNotEqual(self.graph_pages, [], "no page carries a graph")
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                self.assertNotEqual(
                    self.parsed[page].ld_blocks, [],
                    f"{page.name} carries no application/ld+json block")

    def test_a_page_without_a_graph_carries_none(self):
        # The exemption is a statement too. A graph that appeared on an
        # exempted page would be published and read by nobody here.
        for page in WITHOUT_A_GRAPH:
            with self.subTest(page=page.name):
                self.assertIn(page, self.pages, f"{page.name} is not published")
                self.assertEqual(self.parsed[page].ld_blocks, [])

    def test_every_graph_page_was_examined(self):
        # Coverage stated as two numbers rather than assumed. They are equal
        # or this fails; a page the parser could not read is not a page that
        # passed.
        examined = [p for p in self.graph_pages if self.parsed[p].ld_blocks]
        self.assertEqual(
            len(examined), len(self.graph_pages),
            f"examined {len(examined)} of {len(self.graph_pages)} graph pages")

    # --- the shape ----------------------------------------------------------

    def test_every_block_is_valid_json_in_the_schema_org_vocabulary(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                self.graph(page)

    def test_the_graph_describes_the_page_the_site_and_the_software(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                types = {n["@type"] for n in self.graph(page).values()}
                self.assertEqual(
                    types,
                    {"WebSite", "WebPage", "ImageObject",
                     "SoftwareApplication"})

    def test_no_node_points_at_an_id_the_graph_does_not_define(self):
        # `"about": {"@id": ...}` naming a node that is not in the graph is a
        # reference to nothing, and consumers drop it silently rather than
        # complaining. It reads as a described page and is an empty one.
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                nodes = self.graph(page)
                for node in nodes.values():
                    for key, value in node.items():
                        if isinstance(value, dict) and "@id" in value:
                            self.assertIn(
                                value["@id"], nodes,
                                f"{node['@type']}.{key} points at an "
                                f"undefined @id")

    def test_no_property_is_present_but_empty(self):
        # A tag that exists carrying an empty string is absence rendered as a
        # value: it satisfies "the node has a name" and says nothing.
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                for node in self.graph(page).values():
                    for key, value in node.items():
                        where = f"{node['@type']}.{key}"
                        if isinstance(value, str):
                            self.assertTrue(value.strip(), f"{where} is empty")
                        elif isinstance(value, int):
                            self.assertGreater(value, 0, f"{where} is {value}")
                        elif isinstance(value, dict):
                            self.assertTrue(value.get("@id"),
                                            f"{where} references nothing")
                        else:
                            self.fail(f"{where} is a {type(value).__name__}")

    def test_the_block_cannot_break_out_of_its_own_element(self):
        # `</script` inside a JSON string ends the element as far as an HTML
        # parser is concerned, whatever JSON thinks. The generator escapes the
        # three characters that can start markup; this is the check that it
        # still does, stated over the served bytes rather than over the
        # generator's intent.
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                raw = page.read_text(encoding="utf-8")
                start = raw.index('<script type="application/ld+json">')
                end = raw.index("</script>", start)
                body = raw[start + len('<script type="application/ld+json">'):end]
                for character in ("<", ">", "&"):
                    self.assertNotIn(
                        character, body,
                        f"an unescaped {character!r} in the block")

    def test_the_only_scripts_are_inert_data_blocks_and_the_ga4_loader(self):
        # The page promises a reader with no network the same document. A
        # `application/ld+json` block is data: the browser does not execute it
        # and does not fetch anything for it. The one script that runs code is
        # the Google Analytics 4 loader (owner decision 2026-09-17): one inline
        # `<script>` with no type and no `src`, which `tests/test_site.py` and
        # `tests/test_site_analytics.py` hold to the generator's loader by
        # exact text. Any other executable script, or any script with a
        # `src`, would be a different promise, so it fails here rather than
        # being noticed later.
        for page in self.pages:
            with self.subTest(page=page.name):
                code = []
                for script in self.parsed[page].scripts:
                    self.assertNotIn(
                        "src", script,
                        f"{page.name} carries a script that fetches")
                    if script.get("type", "").strip() != "application/ld+json":
                        code.append(script)
                self.assertEqual(
                    code, [{}],
                    f"{page.name} runs code other than the one GA4 loader")

    # --- the derivations ----------------------------------------------------

    def test_the_page_node_repeats_the_pages_own_head(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                head = self.parsed[page]
                webpage = self.node(page, "WebPage")
                self.assertEqual(webpage["name"], head.title)
                self.assertEqual(webpage["description"],
                                 head.meta["description"])
                self.assertEqual(webpage["url"], head.canonical)
                self.assertEqual(webpage["inLanguage"], head.lang)

    def test_the_site_node_repeats_the_pages_own_site_name(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                head = self.parsed[page]
                website = self.node(page, "WebSite")
                self.assertEqual(website["name"], head.meta["og:site_name"])
                self.assertEqual(website["inLanguage"], head.lang)

    def test_the_image_node_repeats_the_card_the_head_names(self):
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                head = self.parsed[page]
                image = self.node(page, "ImageObject")
                self.assertEqual(image["url"], head.meta["og:image"])
                self.assertEqual(image["caption"], head.meta["og:image:alt"])
                self.assertEqual(str(image["width"]),
                                 head.meta["og:image:width"])
                self.assertEqual(str(image["height"]),
                                 head.meta["og:image:height"])

    def test_the_image_nodes_dimensions_are_the_committed_pngs_own(self):
        # The other half of the same claim. The tags and the node can agree
        # with each other and both be wrong about the file, which is what they
        # were before the generator started reading it: two numbers typed once
        # next to a file that has always known the answer.
        card = SITE_DIR / Path(self.parsed[PAGE].meta["og:image"]).name
        self.assertTrue(card.is_file(), f"{card} is not in site/")
        header = card.read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        image = self.node(PAGE, "ImageObject")
        self.assertEqual(
            (image["width"], image["height"]),
            (int.from_bytes(header[16:20], "big"),
             int.from_bytes(header[20:24], "big")),
            "the node states a size the committed PNG does not have")

    def test_the_software_node_repeats_the_packaging_metadata(self):
        software = self.node(PAGE, "SoftwareApplication")
        self.assertEqual(software["alternateName"], self.project["name"])
        self.assertEqual(software["description"], self.project["description"])
        self.assertEqual(
            software["license"],
            SPDX_LICENSE_PAGE.format(self.project["license"]),
            "the license page is not the one the packaging metadata names")

    def test_the_software_version_is_the_committed_runs_own(self):
        # Not `pyproject.toml`'s. The version this page may state is the one
        # the audit it publishes was produced by, and that number is in the
        # report's provenance, inside the run id. It is also already on the
        # page, in the "Harness" row; the node and the row are the same read
        # or this fails.
        software = self.node(PAGE, "SoftwareApplication")
        self.assertEqual(software["softwareVersion"],
                         self.report["provenance"]["harness_version"])
        self.assertIn(f"<code>{software['softwareVersion']}</code>",
                      PAGE.read_text(encoding="utf-8"))

    def test_the_page_the_node_and_the_citation_agree_on_the_repository(self):
        # Three files now state this project's address: the generator, for the
        # links and the node, and `CITATION.cff`, for anyone citing it. They
        # were two copies before the node made it three, so they get held
        # equal rather than left to drift.
        cited = re.search(r'^repository-code:\s*"([^"]+)"',
                          CITATION.read_text(encoding="utf-8"), re.MULTILINE)
        self.assertIsNotNone(cited, "CITATION.cff names no repository-code")
        software = self.node(PAGE, "SoftwareApplication")
        self.assertEqual(software["sameAs"], cited.group(1))
        self.assertTrue(software["@id"].startswith(cited.group(1)))

    def test_the_page_node_and_the_canonical_are_the_published_address(self):
        # This page is served under a project PATH on an origin it shares with
        # five other project sites, so a node claiming the origin would be
        # claiming a document that is not this one.
        for page in self.graph_pages:
            with self.subTest(page=page.name):
                for node in self.graph(page).values():
                    url = node.get("url")
                    if url and url.startswith("https://chelseakr.github.io"):
                        self.assertIn("/plumbline/", url,
                                      f"{node['@type']}.url is the shared "
                                      f"origin, a different site")

    # --- what is deliberately not here --------------------------------------

    def test_it_solicits_no_dataset_harvest(self):
        # Deliberate and permanent, not an oversight to be filled in later.
        #
        # A `Dataset` node, or DCAT beside it, is not a description -- it is an
        # invitation. It exists so that dataset search engines and state
        # open-data catalogs harvest the thing it names and list it as a
        # dataset of record, and a catalog listing is far easier to acquire
        # than to withdraw.
        #
        # `datasets/riverbend-demo/` is an invented county's invented answers,
        # and the page says in as many words that it is a demonstration and
        # not a benchmark. Soliciting its indexing as data would contradict
        # that sentence in a vocabulary the reader of that sentence never
        # sees. The audit reports are not data of record either: they are
        # evidence about this harness, and `plumbline verify` is how a
        # stranger checks one, not a catalog entry.
        #
        # Whether any corpus in this portfolio should ask for that indexing is
        # an open question with an owner's name on it. Saying "this page is
        # about a piece of software" asks for none of it. This test is here so
        # the difference stays a decision somebody makes rather than a line
        # somebody adds.
        forbidden_types = {"Dataset", "DataCatalog", "DataDownload",
                           "DataFeed"}
        forbidden_words = ("dcat:", "dct:", "void:", "distribution",
                           "Dataset", "DataCatalog", "DataDownload",
                           "DataFeed")
        for page in self.pages:
            with self.subTest(page=page.name):
                raw = "".join(self.parsed[page].ld_blocks)
                for word in forbidden_words:
                    self.assertNotIn(word, raw,
                                     f"{word!r} is harvest vocabulary")
                if page in self.graph_pages:
                    for node in self.graph(page).values():
                        self.assertNotIn(node["@type"], forbidden_types)


if __name__ == "__main__":
    unittest.main()

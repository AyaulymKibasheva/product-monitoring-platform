from src.sources import ProductSource, SourceRegistry, SourceRunResult, SourceRunStats


class FakeSource(ProductSource):
    organization_id = "org"
    source_id = "fake"

    def collect(self, *, max_pages=None) -> SourceRunResult:
        return SourceRunResult(self.organization_id, self.source_id, [], SourceRunStats())


def test_registry_resolves_source_by_id() -> None:
    source = FakeSource()
    registry = SourceRegistry([source])

    assert registry.ids() == ("fake",)
    assert registry.get("fake") is source

from DataDictionaryAdminApp.api.schemas_api import AttributeUpsert
from DataDictionaryAdminApp.service.data_dictionary_service import DataDictionaryService


class MinimalRepo:
    def physical_name_exists(self, name, exclude_prj_id=None):
        return False

    def physical_name_for_prj(self, prj_id):
        return None

    def available_physical_name(self, base_name, exclude_prj_id=None):
        return base_name



def _service() -> DataDictionaryService:
    service = DataDictionaryService(db=None)
    service.repo = MinimalRepo()
    service._portfolio_cache = {
        "fi banks": {
            "port_ref_id": 1,
            "portfolio_name": "FI",
            "sector_name": "Banks",
            "label": "FI Banks",
        }
    }
    service._source_name_cache = {}
    service._source_code_cache = {"snpar"}
    service._original_type_cache = {}
    return service



def _auto_payload(prj_id: str, attribute_name: str, generated_physical: str) -> AttributeUpsert:
    # ExcelService supplies the generated value but marks it AUTO when the
    # workbook's physical-name cell was blank.
    return AttributeUpsert(
        prj_id=prj_id,
        portfolio="FI Banks",
        source_abbr_name="SNPAR",
        prj_attribute_name=attribute_name,
        prj_physical_attribute_name=generated_physical,
        physical_name_source="AUTO",
        section="Assets",
        sub_section="Current",
        data_type="Amount",
        calculated_or_reported="Reported",
        display_order=1,
    )



def test_blank_bulk_name_does_not_reuse_stale_staging_name_owned_by_another_final_prj():
    service = _service()
    # Simulates stale staging/raw CFV200 -> tot_assets while Final already owns
    # tot_assets for CFV100. The old single-owner cache could mask CFV100.
    service._physical_owner_cache = {"tot_assets": {"CFV100", "CFV200"}}
    service._physical_by_prj_cache = {"cfv100": "tot_assets", "cfv200": "tot_assets"}

    _, master, _ = service._make_rows(
        _auto_payload("CFV200", "Total Assets", "tot_assets"),
        bulk_physical_policy=True,
    )

    assert master["prj_physical_attribute_name"] == "tot_assets_2"
    assert service._physical_by_prj_cache["cfv200"] == "tot_assets_2"



def test_blank_bulk_names_reserve_unique_values_inside_same_workbook_batch():
    service = _service()
    service._physical_owner_cache = {}
    service._physical_by_prj_cache = {}

    _, master1, _ = service._make_rows(
        _auto_payload("CFV201", "Total Assets", "tot_assets"),
        bulk_physical_policy=True,
    )
    _, master2, _ = service._make_rows(
        _auto_payload("CFV202", "Total Assets", "tot_assets"),
        bulk_physical_policy=True,
    )

    assert master1["prj_physical_attribute_name"] == "tot_assets"
    assert master2["prj_physical_attribute_name"] == "tot_assets_2"



def test_blank_bulk_name_preserves_existing_name_when_only_same_prj_owns_it():
    service = _service()
    service._physical_owner_cache = {"tot_assets": {"CFV200"}}
    service._physical_by_prj_cache = {"cfv200": "tot_assets"}

    _, master, _ = service._make_rows(
        _auto_payload("cfv200", "Total Assets", "tot_assets"),
        bulk_physical_policy=True,
    )

    assert master["prj_physical_attribute_name"] == "tot_assets"

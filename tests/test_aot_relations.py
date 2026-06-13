import shutil
import sqlite3
import unittest
from uuid import uuid4

from test_catalog import TEST_TEMP_ROOT
from test_sql_model import create_sql_model_fixture

TABLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxTable xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>CustSettlement</Name>
  <Relations>
    <AxTableRelation xmlns="" i:type="AxTableRelationForeignKey">
      <Name>CustTable</Name>
      <Cardinality>ZeroMore</Cardinality>
      <EDTRelation>Yes</EDTRelation>
      <RelatedTable>CustTable</RelatedTable>
      <RelatedTableCardinality>ZeroOne</RelatedTableCardinality>
      <RelationshipType>Association</RelationshipType>
      <Constraints>
        <AxTableRelationConstraint xmlns="" i:type="AxTableRelationConstraintField">
          <Name>AccountNum</Name>
          <SourceEDT>CustAccount</SourceEDT>
          <Field>AccountNum</Field>
          <RelatedField>AccountNum</RelatedField>
        </AxTableRelationConstraint>
        <AxTableRelationConstraint xmlns="" i:type="AxTableRelationConstraintFixed">
          <Name>Posting</Name>
          <Field>Posting</Field>
          <Value>1</Value>
        </AxTableRelationConstraint>
      </Constraints>
    </AxTableRelation>
  </Relations>
</AxTable>
"""

EXTENSION_XML = """<?xml version="1.0" encoding="utf-8"?>
<AxTableExtension xmlns:i="http://www.w3.org/2001/XMLSchema-instance">
  <Name>CustTable.MyModel</Name>
  <Relations>
    <AxTableRelation xmlns="" i:type="AxTableRelationForeignKey">
      <Name>MyRefTable</Name>
      <Cardinality>ZeroMore</Cardinality>
      <RelatedTable>MyRefTable</RelatedTable>
      <RelatedTableCardinality>ExactlyOne</RelatedTableCardinality>
      <RelationshipType>Association</RelationshipType>
      <Constraints>
        <AxTableRelationConstraint xmlns="" i:type="AxTableRelationConstraintField">
          <Name>MyRef</Name>
          <Field>MyRef</Field>
          <RelatedField>RecId</RelatedField>
        </AxTableRelationConstraint>
      </Constraints>
    </AxTableRelation>
  </Relations>
</AxTableExtension>
"""


class AotRelationsTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TEMP_ROOT.mkdir(exist_ok=True)
        self.root = TEST_TEMP_ROOT / str(uuid4())
        corpus = self.root / "corpus" / "Pkg" / "Model"
        (corpus / "AxTable").mkdir(parents=True)
        (corpus / "AxTableExtension").mkdir(parents=True)
        (corpus / "AxTable" / "CustSettlement.xml").write_text(TABLE_XML, encoding="utf-8")
        (corpus / "AxTableExtension" / "CustTable.MyModel.xml").write_text(EXTENSION_XML, encoding="utf-8")
        # Compiled copies must be ignored.
        noise = self.root / "corpus" / "Pkg" / "XppMetadata" / "Model" / "AxTable"
        noise.mkdir(parents=True)
        (noise / "CustSettlement.xml").write_text(TABLE_XML, encoding="utf-8")
        self.db = self.root / "sqlmodel.db"
        create_sql_model_fixture(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO sql_tables VALUES(12,'CUSTTABLE','2024-01-01','2024-01-01')")
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_table_and_extension(self) -> None:
        from d365fo_agent.aot_relations import parse_table_relations

        table, element, rels = parse_table_relations(
            self.root / "corpus" / "Pkg" / "Model" / "AxTable" / "CustSettlement.xml", "AxTable")
        self.assertEqual((table, element), ("CustSettlement", "CustSettlement"))
        self.assertEqual(rels[0]["related_table"], "CustTable")
        self.assertEqual(rels[0]["relationship_type"], "Association")
        kinds = {c["kind"] for c in rels[0]["constraints"]}
        self.assertEqual(kinds, {"field", "fixed"})

        table, element, rels = parse_table_relations(
            self.root / "corpus" / "Pkg" / "Model" / "AxTableExtension" / "CustTable.MyModel.xml",
            "AxTableExtension")
        self.assertEqual(table, "CustTable")  # relations belong to the BASE table
        self.assertEqual(element, "CustTable.MyModel")
        self.assertEqual(rels[0]["related_table"], "MyRefTable")

    def test_extract_then_query(self) -> None:
        from d365fo_agent.aot_relations import extract_aot_relations
        from d365fo_agent.sql_model import find_relations, get_sql_model

        stats = extract_aot_relations([self.root / "corpus"], self.db)
        self.assertEqual(stats["files_parsed"], 2)  # XppMetadata copy skipped
        self.assertEqual(stats["relations"], 2)

        rel = find_relations(self.db, "CUSTSETTLEMENT", "CUSTTABLE")
        # No view joins them in the fixture, but the AOT relation is there with join fields.
        aot = rel["aot_relations"]
        self.assertEqual(len(aot), 1)
        self.assertEqual(aot[0]["relationship_type"], "Association")
        fields = {(f["field"], f["related_field"]) for f in aot[0]["join_fields"]}
        self.assertIn(("AccountNum", "AccountNum"), fields)

        table = get_sql_model(self.db, "CUSTSETTLEMENT")
        self.assertEqual(table["aot_relations_count"], 1)
        self.assertEqual(table["aot_relations"][0]["related_table"], "CustTable")

    def test_rerun_replaces(self) -> None:
        from d365fo_agent.aot_relations import extract_aot_relations

        first = extract_aot_relations([self.root / "corpus"], self.db)
        second = extract_aot_relations([self.root / "corpus"], self.db)
        self.assertEqual(first["relations"], second["relations"])  # no duplication


if __name__ == "__main__":
    unittest.main()

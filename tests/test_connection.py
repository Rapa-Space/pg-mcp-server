# tests/test_connection.py — 멀티 DB 헬퍼 단위 테스트 (DB 불필요, stdlib unittest)
import unittest

from server.tools.connection import _dsn_with_db, _validate_db_name, _SYSTEM_DBS


class TestDsnWithDb(unittest.TestCase):
    def test_byte_identity_when_dbname_unchanged(self):
        # 기존 dbname 과 동일하면 원문 바이트 동일 → conn_id == DEFAULT_CONN_ID 보장
        dsn = "postgresql://rp_readonly:pw@host.docker.internal:35432/museum_finder"
        self.assertEqual(_dsn_with_db(dsn, "museum_finder"), dsn)

    def test_swaps_only_path(self):
        dsn = "postgresql://u:p@h:35432/museum_finder"
        self.assertEqual(_dsn_with_db(dsn, "clock_points"), "postgresql://u:p@h:35432/clock_points")

    def test_preserves_query(self):
        dsn = "postgresql://u:p@h:35432/museum_finder?sslmode=require&application_name=x"
        out = _dsn_with_db(dsn, "clock_points")
        self.assertEqual(out, "postgresql://u:p@h:35432/clock_points?sslmode=require&application_name=x")


class TestValidateDbName(unittest.TestCase):
    def test_accepts_app_db_names(self):
        for name in ("clock_points", "museum_finder", "senior_meal_map", "svc-2"):
            _validate_db_name(name)  # 예외 없으면 통과

    def test_rejects_system_dbs_case_insensitive(self):
        for name in ("postgres", "Postgres", "TEMPLATE0", "template1"):
            with self.assertRaises(ValueError):
                _validate_db_name(name)

    def test_rejects_injection(self):
        for name in ("foo?x=1", "a/b", "a b", "x@y", "db;drop", "", "a:b"):
            with self.assertRaises(ValueError):
                _validate_db_name(name)


if __name__ == "__main__":
    unittest.main()

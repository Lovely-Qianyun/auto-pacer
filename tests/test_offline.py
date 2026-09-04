# -*- coding: utf8 -*-
"""离线冒烟测试：不触碰 Zepp/华米任何网络接口，也不读取真实主目录配置。

CI（.github/workflows/tests.yml）在 ubuntu/windows/macos × Python 3.10/3.13 上执行；
本地复现同一命令：python -m pytest tests/ -q
"""

import json
import time

import pytest

import main as app
import util.account_api  # noqa: F401 仅验证模块可导入
import util.aes_help as aes_help
import util.config_store as cs
import util.data_api as data_api
import util.timeutil  # noqa: F401


class TestModuleImport:
    """各模块在三平台/两版本下都能 import（捕捉语法与依赖问题）"""

    def test_all_modules_import(self):
        assert app.STEP_LIMIT_MAX > 0
        assert data_api.DEFAULT_VIRTUAL_DEVICE
        assert aes_help.HM_AES_KEY

    def test_encrypt_roundtrip_shape(self):
        plain = b"a" * 17
        out = aes_help.encrypt_data(plain, aes_help.HM_AES_KEY, aes_help.HM_AES_IV)
        assert len(out) % aes_help.AES_BLOCK_SIZE == 0
        assert out != plain


class TestPureFunctions:
    def test_normalize_phone_adds_prefix(self):
        assert app.normalize_user("13800138000") == "+8613800138000"

    def test_normalize_email_untouched(self):
        assert app.normalize_user("a@b.com") == "a@b.com"

    def test_desensitize_masks(self):
        assert app.desensitize("13800008000") == "138****8000"
        out = app.desensitize("example@example.com")
        assert "example@example.com" not in out

    def test_step_range_coerces_and_sorts(self):
        assert app.validate_step_range("22000", "18000") == (18000, 22000)

    def test_step_range_limit_dynamic(self):
        lo, hi = app.validate_step_range(1, app.STEP_LIMIT_MAX)
        assert (lo, hi) == (1, app.STEP_LIMIT_MAX)
        with pytest.raises(ValueError):
            app.validate_step_range(1, app.STEP_LIMIT_MAX + 1)
        with pytest.raises(ValueError):
            app.validate_step_range(0, 5000)

    @pytest.mark.parametrize("bad", ["abc", None, 1.5, [], {}])
    def test_step_range_rejects_non_int(self, bad):
        with pytest.raises(ValueError):
            app.validate_step_range(bad, 20000)

    def _token_cfg(self, hours_ago):
        return {"app_token": "t", "user_id": "u",
                "app_token_time": str(time.time() * 1000 - hours_ago * 3600 * 1000)}

    def test_token_trust_window(self):
        assert app.app_token_can_be_trusted_locally(self._token_cfg(1)) is True
        assert app.app_token_can_be_trusted_locally(self._token_cfg(25 * 24)) is False
        assert app.app_token_can_be_trusted_locally({}) is False


class TestConfigStore:
    """全程把配置文件重定向到临时目录，绝不碰真实主目录 ~/.auto-pacer.json"""

    def _target(self, monkeypatch, tmp_path):
        target = tmp_path / "cfg.json"
        monkeypatch.setattr(cs, "CONFIG_FILE", str(target))
        return target

    def test_round_trip(self, monkeypatch, tmp_path):
        target = self._target(monkeypatch, tmp_path)
        cfg = {"user": "a@b.com", "pwd": "x", "min_step": 20000,
               "app_token": "tok", "bound_device_id": None}
        cs.save_config(cfg)
        assert json.loads(target.read_text(encoding="utf-8")) == cfg
        assert cs.load_config() == cfg

    def test_missing_returns_empty(self, monkeypatch, tmp_path):
        self._target(monkeypatch, tmp_path)
        assert cs.load_config() == {}

    def test_corrupt_backed_up(self, monkeypatch, tmp_path):
        target = self._target(monkeypatch, tmp_path)
        target.write_text("{not json", encoding="utf-8")
        assert cs.load_config() == {}
        assert (tmp_path / "cfg.json.corrupt").exists()

    def test_atomic_write_no_tmp_residue(self, monkeypatch, tmp_path):
        target = self._target(monkeypatch, tmp_path)
        cs.save_config({"user": "u"})
        assert not (tmp_path / "cfg.json.tmp").exists()
        assert (tmp_path / "cfg.json.lock").exists()  # 尽力锁文件已建立

    def test_default_path_is_home(self):
        assert str(cs.config_path()).replace("\\", "/").endswith("/.auto-pacer.json")


class TestPayload:
    def test_asset_integrity(self):
        payload = data_api._load_payload()
        assert payload.startswith("%5B%7B%22data_hr%22")
        assert payload.endswith("%7D%5D")
        assert "2021-08-07" in payload
        assert data_api.DEFAULT_VIRTUAL_DEVICE in payload

    def test_patch_on_real_asset(self):
        payload = data_api._load_payload()
        out = data_api._patch_payload(payload, "20000", None, "2026-09-03")
        assert "2021-08-07" not in out and "2026-09-03" in out
        assert "20000" in out
        assert data_api.DEFAULT_VIRTUAL_DEVICE in out  # 无真实设备时不替换

    def test_patch_with_real_device(self):
        payload = data_api._load_payload()
        out = data_api._patch_payload(payload, "9999", "AB12CD34EF56", "2026-01-01")
        assert data_api.DEFAULT_VIRTUAL_DEVICE not in out
        assert "AB12CD34EF56" in out

    def test_patch_bad_template_raises(self):
        with pytest.raises(ValueError):
            data_api._patch_payload("no-placeholders", 1, None, "2026-01-01")

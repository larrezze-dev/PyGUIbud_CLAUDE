# Backends abuse-case audit (Step 19d, H50)

Audit of `docs/specs/backends.md` §6 (B1-B16) against the test suite. "existing" = pinned by an
earlier step; "added" = new in `tests/qa/test_step19d_backends.py` (abbreviated `19d` below).

| B | Required behaviour (short) | Test node id(s) | Status |
| --- | --- | --- | --- |
| B1 | `pyside6` without PySide6: `runtime.backend_unavailable` + hint; designer item disabled | `tests/qa/test_step16b_abuse.py::test_b1_without_pyside6_every_entry_refuses_with_the_install_hint`; `tests/qa/test_step16c_abuse.py::test_b1_the_preview_child_without_pyside6_reports_backend_unavailable`; `tests/preview/test_portable_normalise.py::test_b1_a_missing_pyside6_is_backend_unavailable_with_the_install_hint`; `tests/designer/test_preview_toolkit.py` (item "PySide6 (not installed)", disabled) | existing |
| B2 | No display on Linux: `runtime.no_display`, never an abort | `tests/qt/test_qt_process.py::test_b2_no_display_is_refused_before_any_application_exists`; `tests/backends/test_pyside6_backend.py::test_no_display_is_detected_on_x11_platforms`; `tests/qa/test_step16b_abuse.py::test_qa16b_01_a_platform_without_its_display_is_refused` | existing |
| B3 | `load_ui(pyside6)` from a worker thread: `backend_unavailable` | `tests/qt/test_qt_session_abuse.py::test_b3_load_ui_from_a_worker_thread_is_backend_unavailable` | existing |
| B4 | Markup in labels/titles/translations shown literally | `tests/qa/test_step16b_abuse.py::test_b4_markup_is_literal_in_every_slot` | existing |
| B5 | `&`, `[*]`, 200,000 characters: literal, clipped with a log | `tests/qa/test_step16b_abuse.py::test_b5_a_huge_translation_is_clipped_with_one_log_per_slot`; Tk: `tests/runtime/test_qa_step10_gui.py` (MAX_TEXT_LENGTH clipping) | existing |
| B6 | `tb:bootstyle` on 500 widgets: one log line | `tests/qa/test_step16b_abuse.py::test_b6_five_hundred_bootstyles_give_one_log` (Qt); `tests/runtime/test_tkinter_backend.py::test_a_tb_bootstyle_gives_one_log_line` (Tk) | existing |
| B7 | Tk colour name Qt does not know: logged, default background | `tests/qa/test_step16b_abuse.py::test_b7_tk_colours_qt_does_not_know_are_logged` | existing |
| B8 | Undecodable image: logged, no image, build goes on | `tests/qt/test_qt_session_abuse.py::test_b8_an_image_qt_cannot_decode_is_logged_and_left_out` | existing |
| B9 | Tk + Qt in one process: both build, warning logged once | `tests/qt/test_qt_process.py::test_b9_tk_and_qt_interfaces_in_one_process`; 19d `test_b9_the_mixed_toolkit_warning_is_logged_once_for_two_qt_builds` (subprocess) | existing + added (QA-19d-01 fixed) |
| B10 | `load_ui` twice / `run()` in a running loop | `tests/qt/test_qt_session_abuse.py::test_b10_two_interfaces_share_the_one_application`; `tests/qt/test_qt_process.py::test_b10_run_inside_a_running_loop_returns_at_once` | existing |
| B11 | Closing main with a dialog shown ends the session; later use: `runtime.destroyed` | `tests/qt/test_qt_session_abuse.py::test_b11_closing_the_main_window_with_a_dialog_shown_ends_the_session`; Tk: `tests/runtime/test_qa_step10_gui.py::test_closed_main_window_reports_destroyed` | existing |
| B12 | IntVar Entry gets `abc`: no exception/change call, variable unchanged | Qt: `tests/qt/test_qt_behaviour.py::test_b12_an_int_entry_showing_text_keeps_the_last_value`; `tests/qa/test_step16c_abuse.py::test_qa16c_05_text_converts_as_tkinter_get_does`; Tk: 19d `test_b12_an_int_entry_receiving_text_raises_nothing_and_keeps_the_variable[ttkbootstrap, tkinter]` | existing (Qt) + added (Tk) |
| B13 | `minimum > maximum`: inverted slider / sorted spin range + log | Qt: `tests/qt/test_qt_session_abuse.py::test_b13_inverted_ranges_do_not_crash`; `tests/qa/test_step16b_abuse.py::test_b13_extreme_ranges_build_sorted_ranges`; `tests/qa/test_step16c_abuse.py::test_b13_bound_ranges_survive_extreme_variable_values`; Tk: 19d `test_b13_inverted_ranges_build_on_tk_without_a_crash[ttkbootstrap, tkinter]` | existing (Qt) + added (Tk) |
| B14 | Hand-edited `preview_backend` (`"pyside6; rm -rf"`, `""`, 10 KB): fallback to ttkbootstrap | `tests/designer/test_preview_toolkit.py::test_b14_a_malformed_setting_falls_back`; `tests/designer/test_qa16a_abuse.py::test_qa16a_02_an_unknown_saved_toolkit_previews_with_ttkbootstrap`; 19d `test_b14_a_hand_edited_settings_file_on_disk_falls_back` (file round-trip) | existing + added |
| B15 | Third-party backend crashes on load / has no host: `backend_failed` / `backend_unavailable`, designer unaffected | `tests/qa/test_step16a_abuse.py::test_qa16a_06_a_raising_preview_host_is_backend_unavailable`, `::test_a_fork_that_crashes_on_import_is_backend_unavailable`; `tests/core/test_smoke.py::test_registry_isolation_and_resolution`; 19d `test_b15_a_backend_that_crashes_on_load_is_backend_unavailable`, `test_b15_the_crash_is_diagnosed_and_the_registry_stays_usable`, `test_b15_a_backend_without_a_host_is_backend_unavailable_for_the_preview` | existing + added (entry-point route through `load_ui`) |
| B16 | 10,000 widgets with pyside6 in <= 5 s (`slow`) | `tests/qt/test_qt_session_abuse.py::test_b16_ten_thousand_widgets_build_within_five_seconds` (`slow`); 19d `test_b16_a_thousand_widgets_build_quickly_with_pyside6` (default-run smoke, 1,000 widgets) | existing + added |

## Notes
- `slow` is **not** excluded from the default run (`pyproject.toml` `addopts` has no `-m`), so the
  existing 10,000-widget B16 test runs by default; it already is `slow`-marked. The 19d test
  adds a 1,000-widget smoke with the same 5 s bound.
- Not covered by an automated test: the designer status-bar wording for B15 (the registry
  diagnostics and the `UiError` codes are pinned; the status-bar text itself is not).
- QA-19d-01 (fixed by the orchestrator): the mixed-toolkit warning is now logged once per live Tk root (`_qt.py` `_build`), not once per Qt build.
- B13 on Tk: the spec wording ("inverted slider / sorted spin range") is the Qt mapping; Tk keeps
  `from`/`to` as written and draws natively, which the 19d test pins.

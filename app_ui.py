"""Japanese desktop workflow around the existing experiment engine."""

import asyncio
import base64
import hashlib
import io
import os
import unicodedata
from pathlib import Path
from uuid import uuid4

from app_presets import (APP_VERSION, BUILTIN_PRESETS, FOOD_PRESETS, STARTER, apply_parameters,
                         connection_feedback, delete_preset, load_user_presets, register_preset)
from grid_view import draw_grid, PLOT_LOCK
from experiment_task import ExperimentTask
from agent_view import (ICONS, agent_heading, attack_victims, display_message, event_steps,
                        icon_path, step_pages, page_numbers)
from translations import (TranslationBusyError, load_translations,
                          translated_fields, has_untranslated, translate_result)
from run_data import experiment_date, locate_run_directory, read_run, saved_runs, rename_run
from response_fields import decision_notice, reading_fields
from llm_api import REASONING_EFFORTS, REASONING_FORMATS, REASONING_MODES, TOKEN_LIMIT_PARAMETERS, request_options

ROOT = Path(__file__).resolve().parent
LIVE_BOARD_WIDTH = 520


def translate_for_reading(st, result, connection):
    progress = st.progress(0.0, text="日本語に翻訳しています…")
    try:
        cache = asyncio.run(translate_result(
            result, connection,
            on_progress=lambda done, total: progress.progress(done / total, text=f"日本語に翻訳しています… {done} / {total}")))
        if has_untranslated(result, cache):
            st.info("一部を翻訳できませんでした。その箇所は原文で表示します。")
    except TranslationBusyError:
        st.info("別のウィンドウでこの実験を翻訳しています。完了後に表示を更新すると訳文を読めます。")
    except (OSError, ValueError):
        st.warning("日本語訳を保存できませんでした。実験の記録は保存済みです。")
    finally:
        progress.empty()


def pagination(st, run_id, total, location):
    key = f"timeline_page_{run_id}"
    current = max(1, min(st.session_state.get(key, 1), total))
    st.session_state[key] = current
    numbers = page_numbers(total, current)
    buttons = [("≪", 1), ("〈", current - 1)]
    if numbers[0] > 1:
        buttons.append(("…", None))
    buttons.extend((str(number), number) for number in numbers)
    if numbers[-1] < total:
        buttons.append(("…", None))
    buttons.extend((("〉", current + 1), ("≫", total)))
    def change_page(value):
        st.session_state[key] = value
        if location == "bottom":
            st.session_state[f"timeline_jump_{run_id}"] = (None, uuid4().hex)
    for index, (column, (label, target)) in enumerate(zip(st.columns(len(buttons)), buttons)):
        if target is None:
            column.write("…")
        else:
            column.button(label, key=f"{key}_{location}_{index}",
                          disabled=target == current or not 1 <= target <= total,
                          type="primary" if label == str(current) else "secondary",
                          on_click=change_page, args=(target,), width="stretch")
    return current


def step_anchor(run_id, step):
    return f"timeline-{hashlib.sha256(run_id.encode()).hexdigest()[:16]}-step-{int(step)}"


def jump_to_step(st, run_id, step, page, popover_key):
    st.session_state[f"timeline_page_{run_id}"] = page
    st.session_state[f"timeline_agent_{run_id}"] = None
    st.session_state[popover_key] = False
    st.session_state[f"timeline_jump_{run_id}"] = (step, uuid4().hex)


def timeline_legend(st, result, pages):
    occurrences = event_steps(result["logs"])
    page_for_step = {snapshot["step"]: number for number, page in enumerate(pages, 1) for snapshot in page}
    run_id = result["run_id"]
    st.html("""<style>
        .st-key-timeline_legend [data-testid="stPopoverButton"]:not(:disabled) {
            color:#111; text-decoration:underline; text-underline-offset:3px;
        }
        .st-key-timeline_legend [data-testid="stPopoverButton"] {padding:0; min-height:0;}
        </style>""")
    with st.container(horizontal=True, gap="small", vertical_alignment="center", key="timeline_legend"):
        for state, (face, label, _) in ICONS.items():
            if state in occurrences:
                steps = occurrences[state]
                if steps:
                    key = f"timeline_events_{run_id}_{state}"
                    with st.popover(f"{face} {label}", type="tertiary", key=key, on_change="rerun"):
                        for step in steps:
                            st.button(f"Step {step}", type="tertiary", key=f"{key}_{step}",
                                      on_click=jump_to_step, args=(st, run_id, step, page_for_step[step], key))
                else:
                    st.markdown(f":gray[{face} {label}]", width="content")
            elif state == "resource":
                image = base64.b64encode(icon_path(state).read_bytes()).decode("ascii")
                st.html(f'<span style="color:#808495;white-space:nowrap"><img src="data:image/png;base64,{image}" '
                        f'alt="{label}" style="height:1.2em;vertical-align:middle"> {label}</span>', width="content")
            else:
                suffix = {"hungry": "（50未満）", "comfortable": "（150以上）"}.get(state, "")
                st.markdown(f":gray[{face} {label}{suffix}]", width="content")


def scroll_to_requested_step(st, run_id):
    requested = st.session_state.pop(f"timeline_jump_{run_id}", None)
    if requested is None:
        return
    step, token = requested
    target = ("document.querySelector('[data-testid=\"stMain\"]')" if step is None
              else f"document.getElementById('{step_anchor(run_id, step)}')")
    scroll = ("scrollTo({top:0, behavior:'instant'})" if step is None
              else "scrollIntoView({block:'start', behavior:'instant'})")
    # None requests the page top; an integer retains the existing step jump.
    # Only fixed selectors, a hashed run ID and a generated token enter here.
    st.html(f"""<script>
        (() => {{
            // {token}
            const jump = () => {{
                const heading = {target};
                if (!heading) return false;
                heading.{scroll};
                return true;
            }};
            requestAnimationFrame(() => {{
                if (jump()) return;
                const observer = new MutationObserver(() => {{if (jump()) observer.disconnect();}});
                observer.observe(document.body, {{childList:true, subtree:true}});
                setTimeout(() => observer.disconnect(), 5000);
            }});
        }})();
        </script>""", unsafe_allow_javascript=True)


def show_agent(st, snapshot, agent, event, cache, japanese):
    fields, translated = translated_fields(cache, snapshot["step"], event)
    if not japanese:
        fields = reading_fields(event)
    with st.container(border=True):
        st.markdown(f"**{agent_heading(agent, event, attack_victims(snapshot['events']))}**")
        if decision_notice(event):
            st.caption(decision_notice(event))
        st.text(f"💬 {display_message(fields.get('message'))}")
        st.text(f"💭 {fields.get('thought') or '（記録なし）'}")
        with st.expander("詳しく"):
            st.caption(f"体力 {event['energy_before']} → {event['energy_after']}")
            if "turn_energy_cost" in event:
                st.caption(f"ターン末の共通消費 {event['turn_energy_cost']}："
                           f"体力 {event['turn_energy_before']} → {event['turn_energy_after']}")
            if event.get("response_repairs"):
                st.caption(f"応答を補完: {event['normalized_action']}")
            if event.get("retry_count"):
                st.caption("斜め移動のため、同じターン内で移動先を選び直しました。")
                for attempt in event.get("decision_attempts", []):
                    if attempt.get("feedback_prompt"):
                        st.caption("コードから伝えたNG理由と移動先の候補")
                        st.text(attempt["feedback_prompt"])
                    st.caption(f"{attempt['attempt']}回目の応答（原文）")
                    st.text(attempt.get("raw_response", ""))
            for name, label in (("summary", "状況の要約"), ("memory", "次回へ残す記憶")):
                if fields.get(name):
                    if (name == "memory" and event.get("decision_source") == "fallback"
                            and event.get("memory_source") != "engine"):
                        label = "出力された記憶（次回には未採用）"
                    st.caption(label)
                    st.text(fields[name])
            st.caption(f"行動: {event.get('executed_action') or 'なし'}")
            statuses = {"executed": "実行", "rejected": "不成立", "skipped_dead": "死亡で未実行",
                        "sent": "送信済み", "not_requested": "指定なし", "fallback": "エラーで待機"}
            for name, label in (("share", "共有"), ("attack", "攻撃"), ("message", "発言")):
                state = event.get(f"{name}_status")
                if state:
                    st.caption(f"{label}: {statuses.get(state, state)}")
            if event.get("decision_status") != "ok" or event.get("action_status") != "executed":
                st.caption(f"状態: {event.get('action_status')} / {event.get('error_kind') or event.get('reason', '')}")
            if (event.get("error_kind") == "parse_error" or event.get("response_repairs")) and event.get("raw_response"):
                st.caption("応答の原文（補完前）" if event.get("response_repairs") else "応答の原文（形式エラー）")
                st.text(event["raw_response"])
            if japanese and not translated:
                st.caption("この箇所は原文です。")


def show_result(st, result, connection=None, japanese=None):
    import pandas as pd
    try:
        result["output_dir"] = str(locate_run_directory(result))
    except ValueError:
        st.warning("この実験の保存先が見つかりません。「保存した実験」から開き直してください。")
        return
    if result.get("demo_notice"):
        st.info(result["demo_notice"])
    elif result["status"] == "interrupted":
        st.info(f"実験を停止しました。完了した {result['logs'][-1]['step']} ターンまでの記録を保存しています。")
    elif result["status"] != "completed":
        st.warning(f"実験の状態: {result['status']}。エラーを含む場合は待機に置き換えて進んだ記録です。")
    summary = result["summary"]
    for column, key in zip(st.columns(4), ("alive", "total_born", "total_died", "total_actions")):
        column.metric({"alive": "生存", "total_born": "誕生", "total_died": "死亡", "total_actions": "判断回数"}[key], summary.get(key, 0))
    if summary.get("repaired_decisions"):
        st.caption(f"応答を補完した判断: {summary['repaired_decisions']}件（各個体の「詳しく」で確認できます）")
    st.caption(f"保存先: {result['output_dir']}")
    model_info = result.get("model", {"id": None, "status": "legacy_unrecorded"})
    label = model_info.get("id") or ("Mock" if model_info.get("status") == "mock" else "未確認")
    date = result.get("execution_date") or experiment_date(result.get("started_at")) or "未記録"
    st.caption(f"実施日: {date}（日本時間） / モデル: {label}")
    if model_info.get("status") in ("changed_during_run", "unverified_after_run"):
        st.warning("実験中のモデル変更、または終了時の照合失敗が記録されています。モデルの詳細を確認してください。")

    st.subheader("統計データ")
    frame = pd.DataFrame([snap["summary"] for snap in result["logs"]]).set_index("step")
    st.line_chart(frame[["alive", "total_born", "total_died"]].rename(
        columns={"alive": "生存", "total_born": "誕生", "total_died": "死亡"}), x_label="ステップ", y_label="個体数")
    with st.expander("数値の詳細"):
        st.dataframe(frame, width="stretch")

    if japanese is None:
        japanese = st.radio("表示する言語", ["日本語", "原文"], horizontal=True,
                            key=f"language_{result['run_id']}") == "日本語"
    cache = load_translations(result)
    offline = result["config"].get("mock_mode") or result.get("demo_notice")
    if not offline and has_untranslated(result, cache):
        st.caption("まだ日本語訳がない箇所は原文を表示しています。")
        if connection:
            st.caption(f"翻訳に使う接続: {connection['model']} · {connection['base_url']}")
            if st.button("未翻訳分を日本語にする", key=f"translate_{result['run_id']}"):
                translate_for_reading(st, result, connection)
                cache = load_translations(result)
    st.subheader("エージェントたちの記録")
    pages = step_pages(result["logs"])
    timeline_legend(st, result, pages)
    agents = sorted({agent["id"] for snap in result["logs"] for agent in snap["agents"]})
    selected_agent = st.selectbox("表示するエージェント", [None, *agents],
                                 format_func=lambda value: "全員" if value is None else f"エージェント {value:02d}",
                                 key=f"timeline_agent_{result['run_id']}")
    config = result["config"]
    with st.expander("開始時の盤面（Step 0）", expanded=True):
        st.caption("行動前の初期状態です。Step 1以降は、そのターンの行動後を表示します。")
        with PLOT_LOCK:
            fig = draw_grid(result["logs"][0], config["grid_size"], config["reproduce_cost"])
            st.pyplot(fig, width="stretch")
            fig.clear()
    if pages:
        current = pagination(st, result["run_id"], len(pages), "top")
        selected = pages[current - 1]
        st.caption(f"Step {selected[0]['step']}–{selected[-1]['step']} · {current} / {len(pages)} ページ")
        for snapshot in selected:
            st.subheader(f"Step {snapshot['step']}", anchor=step_anchor(result["run_id"], snapshot["step"]))
            board, dialogue = st.columns([1, 1.4])
            with PLOT_LOCK:
                fig = draw_grid(snapshot, config["grid_size"], config["reproduce_cost"])
                board.pyplot(fig, width="stretch")
                fig.clear()
            by_id = {agent["id"]: agent for agent in snapshot["agents"]}
            with dialogue:
                for event in snapshot["events"]:
                    if selected_agent is None or selected_agent == event["agent_id"]:
                        show_agent(st, snapshot, by_id[event["agent_id"]], event, cache, japanese)
        pagination(st, result["run_id"], len(pages), "bottom")
    else:
        st.info("まだ完了したステップはありません。")
    with st.expander("保存されたファイル"):
        st.write("実験の記録は、保存先フォルダに自動保存されています。")
        st.markdown("""
- **run.json**：実験の全記録。画面で読み返すためのデータです。
- **manifest.json**：実験の設定・実行状態・モデル情報。
- **steps.csv**：ターンごとの人口や体力などの数値。
- **agents.csv**：エージェントごとの状態と履歴。
- **events.csv**：判断・行動・発言と、その実行結果。
- **steps.jsonl**：ターンごとに追記する実験の記録。
- **translations.ja.json**：日本語訳（翻訳した場合）。
- **img フォルダ**：盤面画像（画像保存をオンにした場合）。
""")
        if os.getenv("SUGARSCAPE_DESKTOP"):
            from folder_picker import open_folder
            open_folder(result["output_dir"], result["run_id"])
        else:
            st.button("Finderで開く", disabled=True, help="デスクトップ版のアプリで使えます。")
        register_run_preset(st, result)
    with st.expander("この実験の設定"):
        st.json(config)
    with st.expander("モデルの記録（版・重みの照合情報）"):
        st.json(model_info)
    scroll_to_requested_step(st, result["run_id"])


def translation_connection(st, defaults):
    connection = st.session_state.get("connection_settings", {})
    generation = {**defaults, **st.session_state.get("experiment_settings", {})}
    return {"base_url": connection.get("base_url", os.getenv("SUGARSCAPE_BASE_URL", defaults["base_url"])),
            "model": connection.get("model", os.getenv("SUGARSCAPE_MODEL", defaults["model"])),
            "api_key": st.session_state.get("session_api_key") or os.getenv("SUGARSCAPE_API_KEY", ""),
            "timeout": generation["timeout"], **request_options(generation)}


def load_result(st, path, key):
    try:
        st.session_state[key] = read_run(path)
    except (OSError, ValueError):
        st.error("保存データを開けませんでした。このアプリで出力したrun.jsonがあるフォルダか確認してください。")


def food_choice(count):
    return next((name for name, preset in FOOD_PRESETS.items()
                 if preset["params"]["spawn_energy_count"] == count), "指定する")


def select_food(st):
    selected = st.session_state.food_choice
    if selected in FOOD_PRESETS:
        st.session_state.setting_spawn_energy_count = FOOD_PRESETS[selected]["params"]["spawn_energy_count"]


def select_custom_food(st):
    st.session_state.setting_spawn_energy_count = st.session_state.custom_spawn_energy_count


def select_experiment_preset(st, presets, defaults):
    selected = st.session_state.experiment_preset
    st.session_state.selected_experiment_preset = selected
    if selected is None:
        return
    # Old and built-in presets do not choose a provider's request protocol.
    generation = st.session_state.get("experiment_settings", {})
    values = apply_parameters(presets[selected], {**defaults, **request_options(generation)})
    for name, value in values.items():
        st.session_state[f"setting_{name}"] = value
    st.session_state.food_choice = food_choice(values["spawn_energy_count"])
    st.session_state.experiment_settings = {**st.session_state.get("experiment_settings", {}), **values}


def remove_experiment_preset(st):
    try:
        delete_preset(st.session_state.experiment_preset)
    except ValueError as error:
        st.session_state.preset_error = str(error)
    except OSError:
        st.session_state.preset_error = "プリセットを削除できませんでした。保存先のアクセス権を確認してください。"
    else:
        st.session_state.experiment_preset = None
        st.session_state.selected_experiment_preset = None
        st.session_state.preset_notice = "プリセットを削除しました。現在の設定と実験記録はそのままです。"


def experiment_presets(st, defaults):
    try:
        user_presets = load_user_presets()
    except (OSError, ValueError):
        user_presets = []
        st.sidebar.warning("登録済みプリセットを読み込めません。同梱プリセットは使用できます。")
    presets = {preset["id"]: preset for preset in [*user_presets, *BUILTIN_PRESETS]}
    st.session_state.setdefault("selected_experiment_preset", "builtin:standard")
    st.session_state.setdefault("experiment_preset", st.session_state.selected_experiment_preset)
    if st.session_state.experiment_preset not in presets:
        st.session_state.experiment_preset = None
        st.session_state.selected_experiment_preset = None
    # The select's closed width stays within the sidebar. Only its open menu
    # grows to fit names, capped by the viewport; other selectboxes are untouched.
    name_width = max(sum(1 if unicodedata.east_asian_width(char) in "WFA" else 0.65
                         for char in preset["name"]) for preset in presets.values()) + 3
    st.html(f"""<style>
        [data-testid="stSelectboxVirtualDropdown"]:has([role="listbox"][aria-label="プリセット"]) {{
            width:min(calc(100vw - 44px), max(var(--trigger-width), {name_width:.2f}em)) !important;
        }}
        [role="listbox"][aria-label="プリセット"] [role="option"] > div {{
            overflow-x:auto; text-overflow:clip; white-space:nowrap;
        }}
        </style>""")
    with st.sidebar:
        selected = st.selectbox("プリセット", list(presets), index=None, key="experiment_preset",
                                format_func=lambda value: presets[value]["name"], placeholder="プリセットを選ぶ",
                                on_change=select_experiment_preset, args=(st, presets, defaults),
                                disabled="experiment_task" in st.session_state,
                                help="選ぶと設定を読み込みます。読み込んだ後も、各項目を自由に調整できます。")
        if selected and presets[selected].get("description"):
            st.caption(presets[selected]["description"])
        st.button("プリセットを削除", key="delete_experiment_preset",
                  disabled=selected is None or not selected.startswith("user:") or "experiment_task" in st.session_state,
                  on_click=remove_experiment_preset, args=(st,), help="自分で登録したプリセットだけ削除できます。")
        if notice := st.session_state.pop("preset_notice", None):
            st.success(notice)
        if error := st.session_state.pop("preset_error", None):
            st.error(error)


def register_run_preset(st, result):
    run_id = result["run_id"]
    with st.form(f"register_preset_{run_id}"):
        name = st.text_input("プリセット名", value=Path(result["output_dir"]).name[:120], max_chars=120)
        st.caption("この実験の世界・個体・砂糖・生成条件を登録します。接続先・モデル・APIキー・保存先は引き継ぎません。")
        if st.form_submit_button("この設定をプリセットに登録", disabled="experiment_task" in st.session_state):
            try:
                preset = register_preset(result, name)
            except ValueError as error:
                st.error(str(error))
            except OSError:
                st.error("プリセットを登録できませんでした。実験フォルダと保存先のアクセス権を確認してください。")
            else:
                st.session_state[f"preset_registered_{run_id}"] = preset["name"]
                st.rerun()
    if name := st.session_state.pop(f"preset_registered_{run_id}", None):
        st.success(f"「{name}」を登録しました。プリセットの先頭に追加されています。")


def settings(st, defaults):
    prior = st.session_state.get("experiment_settings", {})
    for name, value in {**defaults, **STARTER, **prior}.items():
        if name not in ("api_key", "base_url", "model", "mock_mode", "output_dir"):
            st.session_state.setdefault(f"setting_{name}", value)

    experiment_presets(st, defaults)
    # Use the reviewed observation format for every app run, including old presets.
    params = {"prompt_factors": ("spatial_relations", "self_other_identity")}
    st.sidebar.subheader("実験設定")
    params["num_steps"] = st.sidebar.number_input("ターン数", min_value=1, max_value=1000, key="setting_num_steps")
    params["seed"] = st.sidebar.number_input("乱数シード", min_value=0, max_value=2 ** 32 - 1, key="setting_seed",
                                           help="初期配置などの乱数です。LLMの応答まで同じになる保証はありません。")
    connection = st.session_state.get("connection_settings", {})
    st.session_state.setdefault("connection_mode", connection.get("mode", "LLM / APIに接続"))
    st.session_state.setdefault("connection_url", connection.get("base_url", os.getenv("SUGARSCAPE_BASE_URL", defaults["base_url"])))
    st.session_state.setdefault("connection_model", connection.get("model", os.getenv("SUGARSCAPE_MODEL", defaults["model"])))
    st.session_state.setdefault("connection_api_key", st.session_state.get("session_api_key", ""))
    llm_settings = st.sidebar.expander("LLM設定", expanded=False)
    with llm_settings:
        mode = st.selectbox("動作モード", ["LLM / APIに接続", "Mock（待機のみ・通信なし）"], key="connection_mode",
                            help="サーバーとモデルは各自ご用意ください")
        mock = mode.startswith("Mock")
        base_url = st.text_input("APIのベースURL", key="connection_url", disabled=mock,
                                help="例: http://127.0.0.1:8080/v1。/chat/completionsは付けません。")
        model = st.text_input("モデルID", key="connection_model", disabled=mock,
                             help="サーバーが受け付けるIDを入力します。default_modelは既存MLXサーバーで使う別名です。")
        key = st.text_input("APIキー（必要な場合）", type="password", disabled=mock, key="connection_api_key",
                           help="保存ファイルには含めません。空欄ならSUGARSCAPE_API_KEY環境変数を使います。")
    st.session_state.connection_settings = {"base_url": base_url, "model": model, "mode": mode}
    st.session_state.session_api_key = key
    params.update({"base_url": base_url.strip(), "model": model.strip(), "mock_mode": mock,
                   "api_key": key or os.getenv("SUGARSCAPE_API_KEY", "")})
    with llm_settings:
        params["send_temperature"] = st.toggle("Temperatureを送信", key="setting_send_temperature",
                                               help="オフにすると、値を残したままtemperatureを要求から外します。")
        params["temperature"] = st.number_input("応答のゆらぎ（Temperature）", 0.0, 2.0, step=0.1,
                                                 key="setting_temperature", disabled=not params["send_temperature"])
        params["send_top_p"] = st.toggle("Top-pを送信", key="setting_send_top_p",
                                         help="オフにすると、値を残したままtop_pを要求から外します。")
        params["top_p"] = st.number_input("Top-p", 0.01, 1.0, step=0.01, key="setting_top_p",
                                           disabled=not params["send_top_p"])
        reasoning_labels = {"default": "モデルに任せる", "on": "オン", "off": "オフ"}
        params["reasoning_mode"] = st.selectbox("推論", REASONING_MODES, key="setting_reasoning_mode",
                                                format_func=reasoning_labels.__getitem__,
                                                help="モデルに任せる: 設定を送りません。オン／オフ: 接続先に指定した状態を要求します。")
        reasoning_format_labels = {"openai": "OpenAI方式", "chat_template": "ローカルのテンプレート方式"}
        params["reasoning_format"] = st.selectbox("推論の送信方式", REASONING_FORMATS,
                                                  key="setting_reasoning_format",
                                                  format_func=reasoning_format_labels.__getitem__,
                                                  disabled=params["reasoning_mode"] == "default",
                                                  help="OpenAI方式はreasoning_effort、テンプレート方式はchat_template_kwargs内のenable_thinkingとreasoning_effortを送ります。MLXなど、テンプレート引数に対応する接続先で使います。")
        params["reasoning_effort"] = st.selectbox("推論の強さ", REASONING_EFFORTS, key="setting_reasoning_effort",
                                                  disabled=params["reasoning_mode"] != "on",
                                                  help="接続先が対応する強さを選んでください。初期値はmediumです。")
        st.caption("推論の切り替えには接続先の対応が必要です。推論をオフにできないモデルもあります。")
        params["max_tokens"] = st.number_input("最大出力トークン数", min_value=64, max_value=32768, key="setting_max_tokens")
        params["max_tokens_parameter"] = st.selectbox("出力上限の送信形式", TOKEN_LIMIT_PARAMETERS,
                                                       key="setting_max_tokens_parameter",
                                                       help="接続先の仕様に合わせて選びます。max_completion_tokensは推論トークンも上限に含めます。")
        params["timeout"] = st.number_input("応答待ちの上限（秒）", min_value=1.0, key="setting_timeout")

    with st.sidebar.expander("エージェント設定", expanded=False):
        params["num_agents"] = st.slider("最初の個体数", 1, 20, key="setting_num_agents")
        params["population_cap"] = st.number_input("人口の上限", min_value=1, max_value=200, key="setting_population_cap",
                                                  help="生存中の個体数の上限です。既定の60は、元論文の社会的相互作用の実験に合わせています。開始時の個体数とは別の設定です。")
        st.caption("人口上限に達すると繁殖が止まります。")
        params["initial_energy"] = st.number_input("エージェントの体力（初期値）", min_value=1, key="setting_initial_energy",
                                                  help="最初からいる個体の体力です。0以下で死亡します。回復後の体力はこの値を超えられます。")
        params["child_initial_energy"] = st.number_input("出生時のエージェントの体力", min_value=1, key="setting_child_initial_energy",
                                                        help="新しく生まれた個体の体力です。回復後の体力の上限ではありません。")
        params["reproduce_cost"] = st.number_input("繁殖コスト", min_value=1, key="setting_reproduce_cost")
        params["use_mbti"] = st.checkbox("性格設定（MBTI）を使う", key="setting_use_mbti",
                                         help="既定はオフです。オンのときだけ性格の指示と周囲の個体のMBTI情報をLLMへ渡します。人間の性格を測定・再現するものではありません。")
    st.session_state.setdefault("food_choice", food_choice(st.session_state.setting_spawn_energy_count))
    with st.sidebar.expander("砂糖設定", expanded=False):
        food = st.selectbox("砂糖の量", [*FOOD_PRESETS, "指定する"], key="food_choice", on_change=select_food, args=(st,))
        if food == "指定する":
            # Keep the saved value separate from this conditional widget so
            # hiding it or changing pages cannot revive an older input value.
            st.session_state.custom_spawn_energy_count = st.session_state.setting_spawn_energy_count
            params["spawn_energy_count"] = st.number_input("初期の砂糖の数", min_value=0, max_value=10000,
                                                            key="custom_spawn_energy_count",
                                                            on_change=select_custom_food, args=(st,))
        else:
            st.caption(FOOD_PRESETS[food]["description"])
            params["spawn_energy_count"] = FOOD_PRESETS[food]["params"]["spawn_energy_count"]
            st.session_state.setting_spawn_energy_count = params["spawn_energy_count"]
        params["num_clusters"] = st.number_input("砂糖のまとまりの数", min_value=1, max_value=10, key="setting_num_clusters")
        params["cluster_radius"] = st.number_input("砂糖のまとまりの半径", min_value=0, max_value=10, key="setting_cluster_radius")
        params["energy_spawn_rate"] = st.number_input("各ターンの砂糖の追加確率", 0.0, 1.0,
                                                      format="%.3f", key="setting_energy_spawn_rate",
                                                      help="1ターンに砂糖を1か所追加する確率です。0.2は20%で、平均10ターンに2か所追加されます。")
    with st.sidebar.expander("世界設定", expanded=False):
        params["grid_size"] = st.number_input("世界の広さ", min_value=11, max_value=100, key="setting_grid_size",
                                             help="正方形の世界の一辺のマス数です。20なら20×20マスになります。")
        for name, label, description in (
                ("view_range", "視界", "砂糖や他の個体が見え、体力を分け与えられる範囲です。"),
                ("message_range", "通信", "発言が他の個体へ届く範囲です。受信した発言は次のターンに読まれます。")):
            params[name] = st.number_input(f"{label}の範囲（マス）", min_value=0, max_value=50, step=1,
                                          key=f"setting_{name}",
                                          help=description + " 自分から上下左右と斜めへの距離で、0は同じマスだけです。")
            width = min(params["grid_size"], 2 * params[name] + 1)
            whole_world = "（世界全体）" if width == params["grid_size"] else ""
            st.caption(f"{label}：{width} × {width}マス{whole_world}")
        st.caption("世界の端は反対側につながっています。全員が毎ターン1消費します。"
                   "攻撃は合計5消費し、視界内の相手の体力の25％（切り捨て、最大12）を奪います。")
        params["custom_world_prompt"] = st.text_area("世界観の追加指示", key="setting_custom_world_prompt",
                                                     help="空欄では世界のルールと操作方法だけを伝えます。生存や成長の目標は加えません。MBTIはオンのときだけ追加します。入力した文章は実験時に選択したLLM / APIへ送られます。")
    return params, llm_settings


def storage_settings(st, defaults):
    st.session_state.setdefault("output_root", os.getenv("SUGARSCAPE_OUTPUT_DIR", "outputs"))
    st.session_state.setdefault("setting_save_images", defaults["save_images"])
    with st.sidebar.expander("保存設定", expanded=True):
        if os.getenv("SUGARSCAPE_DESKTOP") == "1":
            from folder_picker import choose_folder
            selected = choose_folder(st.session_state.output_root)
            if selected and selected != st.session_state.output_root:
                st.session_state.output_root = selected
                # Send the chosen directory back to the native button before
                # another click, rather than waiting for another widget change.
                st.rerun()
        output_root = st.text_input("保存先", key="output_root")
        save_images = st.checkbox("盤面画像も保存する", key="setting_save_images",
                                  help="各実験フォルダのimgに、初期盤面をstep000.png、以後は毎ターンstep001.pngのように保存します。")
    return output_root, save_images


def saved_experiments(st, output_root, defaults):
    st.subheader("保存した実験")
    st.caption("通信は発生しません")
    japanese = st.radio("表示する言語", ["日本語", "原文"], horizontal=True,
                        key="saved_experiments_language") == "日本語"
    notice = st.session_state.pop("rename_notice", None)
    if notice:
        st.success(notice)
    candidates = saved_runs(output_root)
    if candidates:
        labels = {str(path): label for path, label in candidates}
        if st.session_state.get("saved_experiment") not in labels:
            st.session_state.saved_experiment = next(iter(labels))
        chosen = st.selectbox("開く実験", list(labels), format_func=labels.__getitem__, key="saved_experiment")
        # Keep long date/model names readable even when the selectbox clips them.
        st.text(Path(chosen).parent.name)
        if st.button("この実験を開く", type="primary"):
            load_result(st, chosen, "history_result")
        with st.expander("実験名を編集"):
            with st.form(f"rename_{hashlib.sha256(chosen.encode()).hexdigest()}"):
                name = st.text_input("実験名", value=Path(chosen).parent.name)
                st.caption("保存フォルダの名前も変更します。")
                if st.form_submit_button("名前を保存"):
                    try:
                        renamed = rename_run(chosen, name)
                    except ValueError as error:
                        st.error(str(error))
                    except OSError:
                        st.error("実験名を変更できませんでした。保存先のアクセス権と名前の長さを確認してください。")
                    else:
                        for key in ("result", "history_result"):
                            result = st.session_state.get(key)
                            if result and Path(result["output_dir"]).resolve() == Path(chosen).parent:
                                result["output_dir"] = str(renamed.parent)
                        st.session_state.renamed_experiment = str(renamed)
                        if Path(output_root).expanduser().resolve() == Path(chosen).parent:
                            st.session_state.renamed_output_root = str(renamed.parent)
                        st.session_state.rename_notice = "実験名を変更しました。"
                        st.rerun()
    else:
        st.info("この保存先には、完了したターンを出力済みの実験がまだありません。")
    if "history_result" in st.session_state:
        show_result(st, st.session_state.history_result, translation_connection(st, defaults), japanese=japanese)


def live_board_image(st, task, snapshot):
    """Render each committed board once, not on every progress poll."""
    cached = st.session_state.get("live_board_cache")
    if cached is None or cached[0] is not task or cached[1] is not snapshot:
        with PLOT_LOCK:
            fig = draw_grid(snapshot, task.params["grid_size"], task.params["reproduce_cost"])
            try:
                buffer = io.BytesIO()
                fig.savefig(buffer, format="png", dpi=140)
                cached = (task, snapshot, buffer.getvalue())
            finally:
                fig.clear()
        st.session_state.live_board_cache = cached
    return cached[2]


def experiment_panel(st, run_simulation, params, problem, defaults):
    task = st.session_state.get("experiment_task")
    state = task.state() if task else None
    if state and state["done"]:
        if state["result"] is not None:
            st.session_state.result = state["result"]
        st.session_state.experiment_error = state["error"]
        st.session_state.experiment_notice = state["notice"]
        del st.session_state.experiment_task
        st.session_state.pop("live_board_cache", None)
        st.rerun()

    with st.container(width=520, horizontal=True, horizontal_alignment="center"):
        if task:
            stop = st.button("停止中…" if state["stopping"] else "停止", type="primary", key="stop_experiment",
                             width=170, disabled=state["stopping"])
            if stop:
                task.stop()
                st.rerun()
        else:
            start = st.button("実験をはじめる", type="primary", disabled=bool(problem), width=170)
            if start:
                for key in ("result", "experiment_error", "experiment_notice", "live_board_cache"):
                    st.session_state.pop(key, None)
                task = ExperimentTask(run_simulation, params)
                st.session_state.experiment_task = task
                task.start()
                st.rerun()
        if st.button("結果をクリア", disabled=task is not None, width=150,
                     help="表示だけを消します。保存済みの実験は残ります。"):
            for key in ("result", "experiment_error", "experiment_notice", "live_board_cache"):
                st.session_state.pop(key, None)

    # Separate slots explicitly clear the last result when a new run starts.
    live_display = st.empty()
    result_display = st.empty()
    if task:
        with live_display.container(key="live_panel"):
            snapshot = state["snapshot"]
            translated = state["translation_progress"]
            if state["stopping"]:
                st.progress(0.0, text="停止して記録を保存しています…")
            elif translated is not None:
                done, total = translated
                st.progress(done / total if total else 0.0, text=f"日本語に翻訳しています… {done} / {total}")
            elif snapshot:
                progress = state.get("decision_progress")
                detail = ""
                if progress:
                    step, received, total = progress
                    detail = f" · Step {step} の応答 {received} / {total} 個体"
                st.progress(min(1.0, snapshot["step"] / task.params["num_steps"]),
                            text=f"{snapshot['step']} / {task.params['num_steps']} ターン · 生存 {snapshot['summary']['alive']} 個体{detail}")
            else:
                st.progress(0.0, text="実験の開始準備をしています…")
            with st.container(horizontal=True, wrap=False, gap="small", key="live_experiment"):
                with st.container(width=LIVE_BOARD_WIDTH, height=LIVE_BOARD_WIDTH, border=False):
                    if snapshot:
                        st.image(live_board_image(st, task, snapshot), width=LIVE_BOARD_WIDTH)
                with st.container(height=LIVE_BOARD_WIDTH, border=False, autoscroll=True, key="live_dialogue"):
                    st.text("\n\n".join(state["recent"]))
    else:
        with result_display.container():
            if st.session_state.get("experiment_error"):
                st.error(st.session_state.experiment_error)
            if st.session_state.get("experiment_notice"):
                st.info(st.session_state.experiment_notice)
            if "result" in st.session_state:
                show_result(st, st.session_state.result, translation_connection(st, defaults))


def run_streamlit_ui(run_simulation, defaults, format_decision, check_connection):
    import streamlit as st
    st.set_page_config(page_title="LLM SugarScape", page_icon=str(ROOT / "assets/branding/app-icon.png"), layout="wide")
    st.html("""<style>
        .st-key-stop_experiment button {background-color:#1976d2; border-color:#1976d2; color:white;}
        .st-key-stop_experiment button:hover {background-color:#1565c0; border-color:#1565c0; color:white;}
        .st-key-stop_experiment button:disabled {background-color:#1976d2; border-color:#1976d2; color:white; opacity:0.55;}
        .st-key-live_panel [data-stale="true"], .st-key-stop_experiment[data-stale="true"] {opacity:1 !important;}
        </style>""")
    st.image(str(ROOT / "assets/branding/llm-sugar-scape-logo.png"), width=520)
    active = "experiment_task" in st.session_state
    if "renamed_experiment" in st.session_state:
        st.session_state.saved_experiment = st.session_state.pop("renamed_experiment")
    if "renamed_output_root" in st.session_state:
        st.session_state.output_root = st.session_state.pop("renamed_output_root")
    st.sidebar.caption(f"デスクトップ版 · {APP_VERSION}" if os.getenv("SUGARSCAPE_DESKTOP") else f"開発画面 · {APP_VERSION}")
    page = st.sidebar.radio("表示", ["実験をつくる", "保存した実験"], disabled=active)
    if page == "実験をつくる":
        params, llm_settings = settings(st, defaults)
    output_root, save_images = storage_settings(st, defaults)

    if page == "保存した実験":
        saved_experiments(st, output_root, defaults)
        return

    params["output_dir"] = output_root
    params["save_images"] = save_images
    st.session_state.experiment_settings = {name: value for name, value in params.items()
                                           if name not in ("api_key", "base_url", "model", "mock_mode", "output_dir")}
    problem = ""
    if params["num_agents"] > params["population_cap"]:
        problem = "人口の上限を、最初の個体数以上にしてください。"
    elif params["spawn_energy_count"] > params["grid_size"] ** 2:
        problem = "砂糖の数を、世界のマス数以下にしてください。"
    elif not params["mock_mode"] and (not params["base_url"] or not params["model"]):
        problem = "APIのベースURLとモデルIDを入力してください。"
    if problem:
        st.sidebar.error(problem)
    probe_key = (params["base_url"], params["model"], hashlib.sha256(params["api_key"].encode()).hexdigest(),
                 params["temperature"], params["max_tokens"], params["top_p"], params["timeout"],
                 *request_options(params).values())
    with llm_settings:
        if params["mock_mode"]:
            st.info("Mockは全個体が待機する動作確認です。LLM実験とは区別して保存します。")
        if st.button("接続テスト", disabled=active or bool(problem) or params["mock_mode"],
                     help="実験用の形式の応答が返るか、1回生成して確認します。"):
            with st.spinner("応答の形式まで確認しています…"):
                try:
                    event = asyncio.run(check_connection(params))
                    ok, message = connection_feedback(event)
                    # The widget owns the key for this session. Keep only safe probe
                    # results here; do not persist model output or credentials.
                    st.session_state.connection_report = (probe_key, ok, message)
                except (ValueError, OSError):
                    st.session_state.connection_report = (probe_key, False,
                        "接続設定を確認してください。ベースURLはhttp://またはhttps://から始め、認証情報をURLに含めないでください。")
        report = st.session_state.get("connection_report")
        if report and report[0] == probe_key and not params["mock_mode"]:
            (st.success if report[1] else st.error)(report[2])

    @st.fragment(run_every=0.5 if active else None)
    def render_experiment():
        experiment_panel(st, run_simulation, params, problem, defaults)
    render_experiment()

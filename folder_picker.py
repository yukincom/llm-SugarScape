"""Folder buttons using the desktop window's existing native bridge."""

import streamlit as st


_picker = st.components.v2.component(
    "output_folder_picker",
    html='<button type="button" disabled>保存先を選ぶ</button><p role="status"></p>',
    css="""
    button {
        width: 100%; min-height: 2.5rem; padding: .45rem .75rem;
        font: inherit; color: var(--st-text-color);
        background: var(--st-background-color); border: 1px solid var(--st-border-color);
        border-radius: .5rem; cursor: pointer;
    }
    button:hover { border-color: var(--st-primary-color); color: var(--st-primary-color); }
    button:disabled { cursor: wait; opacity: .6; }
    p { font: inherit; font-size: .875rem; margin: .35rem 0 0; }
    p:empty { display: none; }
    """,
    js="""
    export default function({parentElement, data, setTriggerValue}) {
        const button = parentElement.querySelector('button');
        const status = parentElement.querySelector('[role="status"]');
        const opening = data.action === 'open';
        const method = opening ? 'open_experiment_directory' : 'choose_output_directory';
        button.textContent = opening ? 'Finderで開く' : '保存先を選ぶ';
        let disposed = false;
        const ready = () => {
            button.disabled = !window.pywebview?.api?.[method];
        };
        ready();
        window.addEventListener('pywebviewready', ready);
        button.onclick = async () => {
            button.disabled = true;
            status.textContent = '';
            try {
                if (opening) {
                    await window.pywebview.api.open_experiment_directory(data.directory, data.run_id);
                } else {
                    const selected = await window.pywebview.api.choose_output_directory(data.directory);
                    if (selected && !disposed) setTriggerValue('selected', selected);
                }
            } catch (error) {
                if (!disposed) status.textContent = opening
                    ? '保存フォルダを開けませんでした。移動・削除されていないか確認してください。'
                    : 'フォルダを選べませんでした。もう一度お試しください。';
            } finally {
                if (!disposed) ready();
            }
        };
        return () => {
            disposed = true;
            window.removeEventListener('pywebviewready', ready);
            button.onclick = null;
        };
    }
    """,
)


def choose_folder(current):
    # A transient event avoids overwriting later manual edits with an old choice.
    # A state default with this name would mask the incoming trigger value.
    result = _picker(data={"directory": current},
                     on_selected_change=lambda: None, key="output_folder_picker")
    return result.selected


def open_folder(directory, run_id):
    _picker(data={"action": "open", "directory": directory, "run_id": run_id},
            key=f"open_saved_folder_{run_id}")

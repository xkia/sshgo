import sys
import traceback

from i18n import i18n
import tui_forms


AUTO_GENERATED_SOURCES = frozenset({"ssh_config_group", "recent_group"})
READONLY_SOURCES = frozenset({"ssh_config", "history"})


def count_descendants(node):
    total = 0
    for child in node.get("children", []) or []:
        total += 1
        total += count_descendants(child)
    return total


def delete_impact_text(tui, node):
    if node.get("type") == "group":
        return i18n.get(
            "delete_group_impact",
            count=count_descendants(node),
        )
    host, port = tui.host_manager.raw_host_port(node)
    target = tui.host_manager._target_display(node.get("user", ""), host, port)
    return i18n.get("delete_host_impact", target=target)


def show_readonly_error(tui):
    tui._show_message(
        i18n.get("readonly_title"),
        "\n".join(
            [
                i18n.get("edit_ssh_config_not_supported"),
                i18n.get("edit_ssh_config_advice"),
            ]
        ),
    )


def show_save_error(tui):
    show_error(
        tui,
        getattr(tui.host_manager, "last_save_error", None)
        or i18n.get("config_save_conflict"),
    )


def show_error(tui, message):
    tui._show_message(i18n.get("error_title"), message)


def show_success(tui, message):
    tui._show_message(i18n.get("success_title"), message)


def run_add_flow(tui, preselected_parent=None):
    original_mode = tui.mode
    try:
        if preselected_parent:
            if not tui._is_editable_parent(preselected_parent):
                show_readonly_error(tui)
                return
            parent_node = preselected_parent
        else:
            tui.mode = "select_parent"
            parent_node = tui.run()
            if not parent_node:
                return

        parent_name = None if parent_node.get("type") == "system" else parent_node["name"]
        parent_id = None if parent_node.get("type") == "system" else parent_node.get("id")

        node_type_fields = tui_forms.node_type_form_fields()
        type_data = tui._run_form_loop(
            node_type_fields,
            i18n.get("select_node_type"),
        )
        if not type_data:
            return

        node_type = type_data["type"]

        if node_type == "host":
            form_fields = tui_forms.host_form_fields(
                include_proxy=parent_node.get("type") != "host",
                advanced_open=False,
            )
            title = i18n.get("add_new_host")
        else:
            form_fields = tui_forms.group_form_fields()
            title = i18n.get("add_new_group")

        def validate_add_form(form_data):
            clean_data = tui_forms.clean_form_data(form_data)
            if (
                clean_data.get("name")
                and clean_data["name"] != parent_node.get("name")
                and clean_data["name"] != "Top Level"
            ):
                existing_node, _, _ = tui.host_manager.find_node_and_parent(
                    clean_data["name"]
                )
                if existing_node:
                    return (
                        [i18n.get("error_name_exists", name=clean_data["name"])],
                        "name",
                    )

            candidate = (
                tui_forms.host_node_from_form(form_data)
                if node_type == "host"
                else tui_forms.group_node_from_form(form_data)
            )
            if parent_id:
                errors = tui.host_manager.validate_add_candidate_by_parent_id(
                    candidate,
                    parent_id,
                )
            else:
                errors = tui.host_manager.validate_add_candidate(
                    candidate,
                    parent_name,
                )
            return (errors, tui._infer_validation_focus(errors))

        final_data = tui._run_form_loop(
            form_fields,
            title,
            validator=validate_add_form,
        )

        if final_data:
            final_data = tui_forms.clean_form_data(final_data)
            if (
                final_data.get("name")
                and final_data["name"] != parent_node.get("name")
                and final_data["name"] != "Top Level"
            ):
                existing_node, _, _ = tui.host_manager.find_node_and_parent(
                    final_data["name"]
                )
                if existing_node:
                    show_error(
                        tui,
                        i18n.get("error_name_exists", name=final_data["name"])
                    )
                    return

            if node_type == "host":
                new_node = tui_forms.host_node_from_form(final_data)
            else:
                new_node = tui_forms.group_node_from_form(final_data)
            if parent_id:
                validation_errors = tui.host_manager.validate_add_candidate_by_parent_id(
                    new_node,
                    parent_id,
                )
            else:
                validation_errors = tui.host_manager.validate_add_candidate(
                    new_node,
                    parent_name,
                )
            if validation_errors:
                show_error(
                    tui,
                    i18n.get("validate_failed") + ":\n" + "\n".join(validation_errors)
                )
                return

            if parent_id:
                saved = tui.host_manager.add_node_to_parent_id(
                    new_node,
                    parent_id,
                )
            else:
                saved = tui.host_manager.add_node(new_node, parent_name)
            if not saved:
                show_save_error(tui)
                return
            show_success(tui, i18n.get("success_added", name=new_node["name"]))
    except Exception as exc:
        tui.restore_screen()
        print(f"An error occurred in add flow: {exc}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        tui.mode = original_mode


def run_edit_flow(tui):
    selected_node = tui.get_current_node()
    if not selected_node or selected_node.get("source") in AUTO_GENERATED_SOURCES:
        return

    if selected_node.get("source") in READONLY_SOURCES:
        show_readonly_error(tui)
        return

    original_name = selected_node["name"]
    selected_id = selected_node.get("id")
    node_type = selected_node["type"]

    if node_type == "host":
        current_host, current_port = tui.host_manager.raw_host_port(selected_node)
        current_auth_val = "none"
        if selected_node.get("password"):
            current_auth_val = "password"
        elif selected_node.get("id_file"):
            current_auth_val = "key"

        values = {
            "name": selected_node.get("name", ""),
            "host": current_host,
            "port": current_port,
            "user": selected_node.get("user", ""),
            "auth": current_auth_val,
            "password": selected_node.get("password", ""),
            "id_file": selected_node.get("id_file", ""),
            "mfa_secret": selected_node.get("mfa_secret", ""),
            "proxy_command": selected_node.get("proxy_command", ""),
            "ssh_jump_mode": selected_node.get("ssh_jump_mode", "default"),
            "transfer_jump_mode": selected_node.get(
                "transfer_jump_mode",
                "default",
            ),
        }
        advanced_open = bool(
            selected_node.get("proxy_command")
            or selected_node.get("ssh_jump_mode")
            or selected_node.get("transfer_jump_mode")
        )
        form_fields = tui_forms.host_form_fields(
            values,
            include_proxy=not selected_node.get("nest_parent"),
            advanced_open=advanced_open,
            include_context=True,
        )
        title = i18n.get("edit_host", name=original_name)
    else:
        form_fields = tui_forms.group_form_fields(selected_node.get("name", ""))
        title = i18n.get("edit_group", name=original_name)

    def validate_edit_form(form_data):
        clean_data = (
            tui_forms.update_data_from_form(form_data)
            if node_type == "host"
            else tui_forms.clean_form_data(form_data)
        )
        if clean_data.get("name") and clean_data["name"] != original_name:
            existing_node, _, _ = tui.host_manager.find_node_and_parent(
                clean_data["name"]
            )
            if existing_node and (
                not selected_id or existing_node.get("id") != selected_id
            ):
                return (
                    [i18n.get("error_name_exists", name=clean_data["name"])],
                    "name",
                )

        if selected_id:
            errors = tui.host_manager.validate_update_candidate_by_id(
                selected_id,
                clean_data,
            )
        else:
            errors = tui.host_manager.validate_update_candidate(
                original_name,
                clean_data,
            )
        return (errors, tui._infer_validation_focus(errors))

    final_data = tui._run_form_loop(
        form_fields,
        title,
        validator=validate_edit_form,
    )

    if final_data:
        final_data = (
            tui_forms.update_data_from_form(final_data)
            if node_type == "host"
            else tui_forms.clean_form_data(final_data)
        )
        if final_data.get("name") and final_data["name"] != original_name:
            existing_node, _, _ = tui.host_manager.find_node_and_parent(
                final_data["name"]
            )
            if existing_node and (
                not selected_id or existing_node.get("id") != selected_id
            ):
                show_error(
                    tui,
                    i18n.get("error_name_exists", name=final_data["name"])
                )
                return

        if selected_id:
            validation_errors = tui.host_manager.validate_update_candidate_by_id(
                selected_id,
                final_data,
            )
        else:
            validation_errors = tui.host_manager.validate_update_candidate(
                original_name,
                final_data,
            )
        if validation_errors:
            show_error(
                tui,
                i18n.get("validate_failed") + ":\n" + "\n".join(validation_errors)
            )
            return

        if selected_id:
            saved = tui.host_manager.update_node_by_id(selected_id, final_data)
        else:
            saved = tui.host_manager.update_node(original_name, final_data)
        if not saved:
            show_save_error(tui)
            return
        tui._recent_group = None
        tui._recent_group_ts = 0
        show_success(tui, i18n.get("success_updated", name=final_data["name"]))


def run_delete_flow(tui):
    selected_node = tui.get_current_node()
    if not selected_node or selected_node.get("source") in AUTO_GENERATED_SOURCES:
        return

    if selected_node.get("source") in READONLY_SOURCES:
        show_readonly_error(tui)
        return

    title = i18n.get("confirm_deletion")
    form_fields = [
        {
            "label": i18n.get("delete_confirm_msg", name=selected_node["name"]),
            "type": "static_text",
        },
        {
            "label": delete_impact_text(tui, selected_node),
            "type": "static_text",
        },
        {
            "label": i18n.get("cancel"),
            "type": "button",
            "name": "cancel",
        },
        {
            "label": i18n.get("delete"),
            "type": "button",
            "name": "confirm",
        },
    ]

    result = tui._run_form_loop(
        form_fields,
        title,
        initial_focus_name="cancel",
    )

    if result and result.get("confirm"):
        if selected_node.get("id"):
            saved = tui.host_manager.delete_node_by_id(selected_node["id"])
        else:
            saved = tui.host_manager.delete_host(selected_node["name"])
        if not saved:
            show_save_error(tui)
            return
        tui.highlight_line_number = max(0, tui.highlight_line_number - 1)

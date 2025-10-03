import streamlit as st
import requests
import os
import re
from datetime import datetime
import zipfile
import io

DEFAULT_CONFLUENCE_URL = "https://confluence.bsh-group.com/"


DEFAULT_SPACE_KEY = ""
FALLBACK_PAGE_TITLE_BASE = "Automated Page FallBack Title"

st.set_page_config(page_title="Docupedia Page Publisher", layout="wide")
st.title("Docupedia Page Publishing Tool")

# --- Initialize Session State ---
if 'page_id' not in st.session_state:
    st.session_state.page_id = None
if 'current_page_version' not in st.session_state:
    st.session_state.current_page_version = None
if 'current_page_title' not in st.session_state:
    st.session_state.current_page_title = None
if 'page_link' not in st.session_state:
    st.session_state.page_link = None
if 'logs' not in st.session_state:
    st.session_state.logs = []

# Tag Collector utility state
if 'tag_collector_input' not in st.session_state:
    st.session_state.tag_collector_input = ""
if 'tag_collector_output' not in st.session_state:
    st.session_state.tag_collector_output = ""


# --- Logging Helper ---
def add_log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.logs.append(f"[{timestamp}] {message}")


# --- Sidebar ---
with st.sidebar:
    st.header("Configuration")
    CONFLUENCE_URL = st.text_input(
        "Confluence URL",
        DEFAULT_CONFLUENCE_URL,
        key="conf_url_input_sidebar"
    )
    SPACE_KEY = st.text_input(
        "Space Key",
        DEFAULT_SPACE_KEY,
        key="space_key_input_sidebar"
    )
    CONFLUENCE_PAT = st.text_input(
        "Confluence PAT",
        type="password",
        help="Your Confluence Personal Access Token.",
        key="pat_input_sidebar"
    )

    st.markdown("---")

    st.header("Tags Collector!")

    current_tag_input = st.session_state.get('tag_collector_input', "")
    st.session_state.tag_collector_input = st.text_input(
        "Enter string to process:",
        value=current_tag_input,  # Persist input using session state
        key="tag_collector_raw_input_sidebar"  # Unique key for this widget
    )

    if st.session_state.tag_collector_input:
        # Process the input string
        processed_string = st.session_state.tag_collector_input.replace("Delete Label", " ")
        st.session_state.tag_collector_output = ' '.join(processed_string.split())  # Remove extra spaces

        st.write("Processed string:")
        st.markdown(
            """
            <div style="margin-top:10px; margin-bottom:20px;">
            """, unsafe_allow_html=True
        )
        st.code(st.session_state.tag_collector_output, language=None)  # Display processed string
        st.markdown("</div>", unsafe_allow_html=True)

    elif not st.session_state.tag_collector_input and st.session_state.get('tag_collector_output'):
        st.session_state.tag_collector_output = ""

    if not st.session_state.get('tag_collector_input') and not st.session_state.get('tag_collector_output'):
        st.caption("Type above to see processed output.")

API_BASE_URL = f"{CONFLUENCE_URL.rstrip('/')}/rest/api" if CONFLUENCE_URL else None
HEADERS_CONTENT = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": f"Bearer {CONFLUENCE_PAT}"
}
HEADERS_ATTACHMENT = {
    "Accept": "application/json",
    "X-Atlassian-Token": "nocheck",
    "Authorization": f"Bearer {CONFLUENCE_PAT}"
}


st.header("1. Page Content & Location")
col1, col2 = st.columns(2)
with col1:
    desired_page_title_from_input = st.text_input(
        "Page Title for Confluence (Optional)",
        FALLBACK_PAGE_TITLE_BASE,
        help="The title you want for the Confluence page. A temporary suffix may be added if Title already Exists."
             " You can Change it Later"
    )
with col2:
    initial_parent_id_input = st.text_input(
        "Parent Page ID (Optional)",
        help="If provided, the new page will be created under this parent. You can Change it Later"
    )

storage_content_input = st.text_area(
    "Paste Confluence Storage Format XML Here",
    height=250,
    placeholder="<p>Your content here...</p><p><ri:attachment ri:filename=\"example.png\" /></p>"
)
storage_content = storage_content_input if storage_content_input.strip() else None

if not storage_content:
    st.info("Paste your Confluence storage format XML into the text area above to begin.")

st.header("2. Attachments (Optional)")
uploaded_files_list = st.file_uploader(
    "Upload attachments: ZIP file(s) or individual files (images, docs, etc.)",
    type=['zip', 'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'svg'],
    accept_multiple_files=True
)

referenced_attachments = []
if storage_content:
    try:
        referenced_attachments = re.findall(r'<ri:attachment[^>]*?ri:filename="([^"]+)"', storage_content)
        #referenced_attachments = re.findall(r'<ri:attachment\s+ri:filename="([^"]+)"[^>]*?/>', storage_content)

        referenced_attachments = list(set(referenced_attachments))
        if referenced_attachments:
            st.write("Attachments referenced in content (by `ri:filename`):", ", ".join(referenced_attachments))
            if uploaded_files_list:
                uploaded_filenames = [f.name for f in uploaded_files_list]
                st.write(f"Uploaded file(s) for attachments: `{', '.join(uploaded_filenames)}`.")
            else:
                st.warning("Content references attachments, but no files have been uploaded yet for them.")
        else:
            st.info("No `<ri:attachment>` tags found in the provided storage content.")
    except Exception as e:
        st.error(f"Error parsing storage content for attachments: {e}")


def create_confluence_page_storage_api(title, space_key, storage_format_data, parent_id, headers, api_base_url,
                                       log_func):
    api_url = f"{api_base_url}/content"
    page_data = {
        "type": "page", "title": title, "space": {"key": space_key},
        "body": {"storage": {"value": storage_format_data, "representation": "storage"}},
    }
    if parent_id:
        page_data["ancestors"] = [{"id": str(parent_id)}]
        log_func(f"Attempting to create page '{title}' in space '{space_key}' under parent ID '{parent_id}'...")
    else:
        log_func(f"Attempting to create page '{title}' in space '{space_key}' (at space root)...")

    try:
        response = requests.post(api_url, headers=headers, json=page_data, timeout=30)
        response.raise_for_status()
        page_info = response.json()
        page_id = page_info.get('id')
        version_number = page_info.get('version', {}).get('number')
        created_title = page_info.get('title')
        web_ui_suffix = page_info.get('_links', {}).get('webui', '')
        page_link_relative = web_ui_suffix if web_ui_suffix and web_ui_suffix.startswith(
            '/') else f"/pages/viewpage.action?pageId={page_id}"
        page_link_full = f"{CONFLUENCE_URL.rstrip('/')}{page_link_relative}"  # Uses CONFLUENCE_URL from sidebar
        log_func(f"SUCCESS: Created page '{created_title}' (ID: {page_id}, Version: {version_number})")
        return {"id": page_id, "link": page_link_full, "version": version_number, "title": created_title}
    except requests.exceptions.HTTPError as e:
        log_func(f"ERROR creating page: {e} (Status {e.response.status_code})")
        try:
            log_func(f"Response content: {e.response.text[:500]}...")
        except Exception:
            log_func("Could not decode error response content.")
    except Exception as e:
        log_func(f"Unexpected error in create_confluence_page_storage_api: {e}")
    return None


def upload_attachment_api(page_id, filename_on_confluence, file_bytes, headers, api_base_url, log_func):
    api_url = f"{api_base_url}/content/{page_id}/child/attachment"
    try:
        files_for_requests = {'file': (filename_on_confluence, file_bytes, 'application/octet-stream')}
        log_func(f"  Uploading as '{filename_on_confluence}' to page ID {page_id}...")
        resp = requests.post(api_url, headers=headers, files=files_for_requests, timeout=60)
        resp.raise_for_status()
        log_func(f"  SUCCESS: Uploaded '{filename_on_confluence}'")
        return True
    except requests.exceptions.HTTPError as e:
        log_func(f"  ERROR uploading '{filename_on_confluence}': {e} (Status {e.response.status_code})")
        if e.response.status_code == 409:
            log_func("  >>> Conflict: Attachment with this name might already exist on the page.")
        elif e.response.status_code == 403:
            log_func("  >>> Forbidden: Check PAT permissions for adding attachments.")
        try:
            log_func(f"  Response content: {e.response.text[:200]}...")
        except Exception:
            log_func("Could not decode error response content.")
    except Exception as e:
        log_func(f"  Unexpected error uploading '{filename_on_confluence}': {e}")
    return False


def move_confluence_page_api(page_id_to_move, current_page_title, space_key, new_parent_id, current_version, headers,
                             api_base_url, log_func):
    api_url = f"{api_base_url}/content/{page_id_to_move}"
    next_version_number = current_version + 1
    move_data = {
        "id": page_id_to_move, "type": "page", "title": current_page_title,
        "space": {"key": space_key}, "ancestors": [{"id": str(new_parent_id)}],
        "version": {"number": next_version_number}
    }
    log_func(
        f"Attempting to move page '{current_page_title}' (ID: {page_id_to_move}, Ver: {current_version}) under parent ID '{new_parent_id}'...")
    try:
        response = requests.put(api_url, headers=headers, json=move_data, timeout=30)
        response.raise_for_status()
        updated_page_info = response.json()
        updated_version = updated_page_info.get('version', {}).get('number')
        log_func(f"SUCCESS: Moved page. New Version: {updated_version}")
        return True, updated_version
    except requests.exceptions.HTTPError as e:
        log_func(f"ERROR moving page: {e} (Status {e.response.status_code})")
        try:
            log_func(f"Response content: {e.response.text[:500]}...")
        except Exception:
            log_func("Could not decode error response content.")
    except Exception as e:
        log_func(f"Unexpected error in move_confluence_page_api: {e}")
    return False, current_version


def update_page_title_api(page_id_to_update, new_page_title, space_key, current_version, headers, api_base_url,
                          log_func):
    api_url = f"{api_base_url}/content/{page_id_to_update}"
    next_version_number = current_version + 1
    update_data = {
        "id": page_id_to_update, "type": "page", "title": new_page_title,
        "space": {"key": space_key}, "version": {"number": next_version_number}
    }
    log_func(
        f"Attempting to update title of page ID '{page_id_to_update}' (Ver: {current_version}) to '{new_page_title}'...")
    try:
        response = requests.put(api_url, headers=headers, json=update_data, timeout=30)
        response.raise_for_status()
        updated_page_info = response.json()
        confirmed_new_title = updated_page_info.get('title')
        updated_version = updated_page_info.get('version', {}).get('number')
        log_func(f"SUCCESS: Updated page title to '{confirmed_new_title}'. New Version: {updated_version}")
        return True, updated_version, confirmed_new_title
    except requests.exceptions.HTTPError as e:
        log_func(f"ERROR updating page title: {e} (Status {e.response.status_code})")
        if e.response and e.response.text:
            error_detail = ""
            try:
                error_json = e.response.json()
                error_detail = error_json.get('message', e.response.text[:500])
            except requests.exceptions.JSONDecodeError:
                error_detail = e.response.text[:500]
            log_func(f"Response content: {error_detail}...")
            if "title already exists" in error_detail.lower():
                log_func("  >>> This often means the new title is already in use in this space.")
        else:
            log_func("Could not decode error response content or response was empty.")
    except Exception as e:
        log_func(f"Unexpected error in update_page_title_api: {e}")
    return False, current_version, None


st.header("3. Create Confluence Page")
if st.button("🚀 Create Page & Upload Attachments",
             disabled=not storage_content or not CONFLUENCE_PAT or not API_BASE_URL):
    if not storage_content:
        st.error("Please provide storage format XML in Step 1.")
    elif not CONFLUENCE_PAT:
        st.error("Please enter your Confluence PAT in the sidebar.")
    elif not API_BASE_URL:
        st.error("Confluence URL in sidebar is not valid or missing.")
    else:
        st.session_state.logs = []
        add_log("Initiating page creation process...")

        user_specified_title_base = desired_page_title_from_input.strip()
        if not user_specified_title_base: user_specified_title_base = FALLBACK_PAGE_TITLE_BASE.strip()

        # current_time_str_suffix = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        title_for_initial_creation = user_specified_title_base

        add_log(f"Desired final page title: '{user_specified_title_base}'")
        add_log(f"Desired title for initial creation: '{title_for_initial_creation}'")
        parent_id_to_use = initial_parent_id_input.strip() if initial_parent_id_input else None

        creation_info = None
        with st.spinner(f"Creating page '{title_for_initial_creation}' on Confluence..."):
            creation_info = create_confluence_page_storage_api(
                title_for_initial_creation, SPACE_KEY, storage_content, parent_id_to_use,
                HEADERS_CONTENT, API_BASE_URL, log_func=add_log
            )

        if creation_info:
            st.session_state.page_id = creation_info["id"]
            st.session_state.current_page_version = creation_info["version"]
            st.session_state.current_page_title = creation_info["title"]
            st.session_state.page_link = creation_info["link"]

            if user_specified_title_base and user_specified_title_base != st.session_state.current_page_title:
                add_log(f"Attempting to update page title to the desired base: '{user_specified_title_base}'...")
                with st.spinner(f"Updating title to '{user_specified_title_base}'..."):
                    title_update_success, new_ver_rename, conf_title = update_page_title_api(
                        st.session_state.page_id, user_specified_title_base, SPACE_KEY,
                        st.session_state.current_page_version, HEADERS_CONTENT, API_BASE_URL, log_func=add_log
                    )
                if title_update_success:
                    st.session_state.current_page_version = new_ver_rename
                    st.session_state.current_page_title = conf_title
                    add_log(f"SUCCESS: Page title updated to '{st.session_state.current_page_title}'.")
                else:
                    add_log(
                        f"WARNING: Failed to update page title to '{user_specified_title_base}'. The page retains the title '{st.session_state.current_page_title}'. This might be due to the desired title already existing in the space.")
                    st.warning(
                        f"Could not update title to '{user_specified_title_base}'. Page remains '{st.session_state.current_page_title}'. (Desired title might already exist).")

            if referenced_attachments and uploaded_files_list:
                add_log(f"\nProcessing attachments for page ID: {st.session_state.page_id}...")
                succ_uploads = 0;
                fail_uploads = 0
                available_attachments_data = {}

                with st.spinner("Preparing attachments from uploads..."):
                    for uploaded_file in uploaded_files_list:
                        original_filename = uploaded_file.name
                        try:
                            file_content_bytes = uploaded_file.getvalue()
                            if original_filename.lower().endswith('.zip'):
                                add_log(f"  Processing ZIP file: '{original_filename}'")
                                try:
                                    with zipfile.ZipFile(io.BytesIO(file_content_bytes), 'r') as zip_ref:
                                        for name_in_zip in zip_ref.namelist():
                                            if name_in_zip.endswith('/'): continue
                                            base_name_in_zip = os.path.basename(name_in_zip)
                                            try:
                                                bytes_in_zip = zip_ref.read(name_in_zip)
                                                if base_name_in_zip in available_attachments_data:
                                                    add_log(
                                                        f"    WARNING: Attachment '{base_name_in_zip}' from '{original_filename}' (path: '{name_in_zip}') overrides a previously found file.")
                                                available_attachments_data[base_name_in_zip] = (
                                                bytes_in_zip, f"{original_filename}/{name_in_zip}")
                                                add_log(
                                                    f"    Found '{base_name_in_zip}' (from '{name_in_zip}') in ZIP.")
                                            except Exception as e_zip_read:
                                                add_log(
                                                    f"    ERROR reading '{name_in_zip}' from ZIP '{original_filename}': {e_zip_read}")
                                except zipfile.BadZipFile:
                                    add_log(
                                        f"  ERROR: Uploaded file '{original_filename}' is not a valid ZIP file or is corrupted.")
                                except Exception as e_zip_proc:
                                    add_log(f"  ERROR processing ZIP file '{original_filename}': {e_zip_proc}")
                            else:
                                base_uploaded_filename = os.path.basename(original_filename)
                                if base_uploaded_filename in available_attachments_data:
                                    add_log(
                                        f"  WARNING: Directly uploaded file '{base_uploaded_filename}' overrides a previously found file.")
                                available_attachments_data[base_uploaded_filename] = (
                                file_content_bytes, original_filename)
                                add_log(f"  Prepared directly uploaded file: '{base_uploaded_filename}'")
                        except Exception as e_file_proc:
                            add_log(f"  ERROR processing uploaded file '{original_filename}': {e_file_proc}")

                if available_attachments_data and referenced_attachments:
                    add_log("Attempting to upload referenced attachments...")
                    with st.spinner("Uploading attachments..."):
                        for ref_fn_in_content in referenced_attachments:
                            filename_on_confluence = os.path.basename(ref_fn_in_content)
                            if filename_on_confluence in available_attachments_data:
                                file_bytes, source_description = available_attachments_data[filename_on_confluence]
                                add_log(f"  Match found for '{filename_on_confluence}' (from '{source_description}').")
                                try:
                                    if upload_attachment_api(st.session_state.page_id, filename_on_confluence,
                                                             file_bytes, HEADERS_ATTACHMENT, API_BASE_URL,
                                                             log_func=add_log):
                                        succ_uploads += 1
                                    else:
                                        fail_uploads += 1
                                except Exception as e_upload_call:
                                    add_log(
                                        f"  ERROR during upload_attachment_api call for '{filename_on_confluence}': {e_upload_call}");
                                    fail_uploads += 1
                            else:
                                add_log(
                                    f"  SKIPPING: Referenced attachment '{filename_on_confluence}' (from content: '{ref_fn_in_content}') not found in uploads.")
                                fail_uploads += 1
                elif referenced_attachments:
                    add_log("No attachable files were processed from uploads, but content references attachments.")

                add_log(f"Attachment upload summary: {succ_uploads} succeeded, {fail_uploads} failed/skipped.")
                if succ_uploads > 0: st.info(f"{succ_uploads} attachments uploaded successfully.")
                if fail_uploads > 0: st.warning(
                    f"{fail_uploads} attachments failed to upload or were skipped. Check logs.")

            elif referenced_attachments:
                add_log("Content references attachments, but no files were provided for upload in Step 2.")
                st.warning("Your content references attachments, but you didn't upload any files in Step 2.")

            st.success(
                f"Page '{st.session_state.current_page_title}' (ID: {st.session_state.page_id}, Ver: {st.session_state.current_page_version}) processed!")
            st.markdown(f"🔗 **View page:** [{st.session_state.current_page_title}]({st.session_state.page_link})")
        else:
            st.error("Page creation failed. Check logs below for details.")
            st.session_state.page_id = None

if st.session_state.page_id:
    st.markdown("---")
    st.header(f"4. Manage Page: '{st.session_state.current_page_title}' (ID: {st.session_state.page_id})")

    with st.expander("↪️ Move Page"):
        new_parent_id_input_move = st.text_input("Enter Target Parent Page ID (for moving)",
                                                 key="move_parent_id_input_main")
        if st.button("Move Page", key="move_page_btn_main",
                     disabled=not new_parent_id_input_move or not CONFLUENCE_PAT or not API_BASE_URL):
            if not CONFLUENCE_PAT:
                st.error("PAT missing in sidebar.")
            elif not API_BASE_URL:
                st.error("Confluence URL invalid/missing in sidebar.")
            else:
                with st.spinner(f"Moving page {st.session_state.page_id} under parent {new_parent_id_input_move}..."):
                    success, new_version = move_confluence_page_api(
                        st.session_state.page_id, st.session_state.current_page_title, SPACE_KEY,
                        new_parent_id_input_move, st.session_state.current_page_version,
                        HEADERS_CONTENT, API_BASE_URL, log_func=add_log
                    )
                if success:
                    st.session_state.current_page_version = new_version
                    st.success(f"Page moved successfully! New version: {new_version}.")
                    add_log(f"SUCCESS: Page moved to be under parent {new_parent_id_input_move}.")
                else:
                    st.error("Page move failed. Check logs."); add_log("ERROR: Page move failed.")

    with st.expander("✏️ Update Page Title"):
        new_title_input_update = st.text_input("Enter New Title for the Page",
                                               value=st.session_state.current_page_title, key="update_title_input_main")
        if st.button("Update Title", key="update_title_btn_main",
                     disabled=not new_title_input_update or new_title_input_update == st.session_state.current_page_title or not CONFLUENCE_PAT or not API_BASE_URL):
            if not CONFLUENCE_PAT:
                st.error("PAT missing in sidebar.")
            elif not API_BASE_URL:
                st.error("Confluence URL invalid/missing in sidebar.")
            else:
                with st.spinner(f"Updating title for page {st.session_state.page_id}..."):
                    success, new_version, confirmed_title = update_page_title_api(
                        st.session_state.page_id, new_title_input_update, SPACE_KEY,
                        st.session_state.current_page_version, HEADERS_CONTENT, API_BASE_URL, log_func=add_log
                    )
                if success:
                    st.session_state.current_page_version = new_version
                    st.session_state.current_page_title = confirmed_title
                    st.success(f"Page title updated to '{confirmed_title}'! New version: {new_version}.")
                    add_log(f"SUCCESS: Page title updated to '{confirmed_title}'.")
                    st.experimental_rerun()
                else:
                    st.error("Page title update failed. Check logs."); add_log("ERROR: Page title update failed.")

    st.markdown(
        f"**Current Page Status:** Title: `{st.session_state.current_page_title}`, ID: `{st.session_state.page_id}`, Version: `{st.session_state.current_page_version}`")
    if st.session_state.page_link:
        st.markdown(f"🔗 **Link:** [{st.session_state.current_page_title}]({st.session_state.page_link})")

st.markdown("---")
st.header("📜 Operation Logs")
with st.expander("View Logs", expanded=True):
    if st.session_state.logs:
        st.markdown("""
            <style>
            .log-container {
                max-height: 300px; 
                overflow-y: auto;  
                border: 1px solid #ddd;
                padding: 10px;
                border-radius: 5px;
                font-family: monospace;
                white-space: pre-wrap; 
                word-wrap: break-word; 
            }
            </style>
        """, unsafe_allow_html=True)

        logs_html_content = "<div class='log-container'>"
        for log_entry in reversed(st.session_state.logs):
            safe_log_entry = log_entry.replace("&", "&").replace("<", "<").replace(">", ">")
            logs_html_content += f"{safe_log_entry}<br>"
        logs_html_content += "</div>"

        st.markdown(logs_html_content, unsafe_allow_html=True)
    else:
        st.caption("No operations performed yet in this session.")

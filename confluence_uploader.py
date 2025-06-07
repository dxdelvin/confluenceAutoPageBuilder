import requests
import os
import xml.etree.ElementTree as ET
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
import argparse
import mimetypes
import glob
import traceback

load_dotenv()

CONFLUENCE_URL = "http://localhost:8090"
CONFLUENCE_USERNAME = os.getenv("CONFLUENCE_USERNAME")
CONFLUENCE_PASSWORD = os.getenv("CONFLUENCE_PASSWORD")
AUTH = HTTPBasicAuth(CONFLUENCE_USERNAME, CONFLUENCE_PASSWORD)
API_BASE = f"{CONFLUENCE_URL}/rest/api"
DEFAULT_JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}


def parse_xml(xml_file_path):
    print(f"\n--- Starting XML Parsing: {xml_file_path} ---")
    try:
        tree = ET.parse(xml_file_path)
    except FileNotFoundError:
        print(f"Error: XML file not found at {xml_file_path}")
        return []
    except ET.ParseError as e:
        print(f"Error: Could not parse XML file {xml_file_path}. Error: {e}")
        return []
    root = tree.getroot()

    body_content_map = {}
    attachment_details_map = {}

    print("\n[XML PARSE - PASS 1] Indexing BodyContent objects...")
    for obj in root.findall('object[@class="BodyContent"]'):
        body_content_id_elem = obj.find('id')
        body_prop_elem = obj.find('property[@name="body"]')
        if body_content_id_elem and body_prop_elem is not None:
            body_content_map[body_content_id_elem.text] = body_prop_elem.text if body_prop_elem.text is not None else ""
    print(f"Found {len(body_content_map)} BodyContent objects.")

    print("\n[XML PARSE - PASS 2] Indexing Attachment objects...")
    for obj in root.findall('object[@class="Attachment"]'):
        attachment_id_elem = obj.find('id')
        file_name_elem = obj.find('property[@name="fileName"]')
        # This 'container' is the Page/BlogPost the attachment originally belonged to
        container_ref_elem = obj.find('reference[@name="container"]/id')
        original_container_id = container_ref_elem.text if container_ref_elem is not None else None

        attachment_id_text = attachment_id_elem.text if attachment_id_elem is not None else "N/A_ID"
        file_name_text = file_name_elem.text if file_name_elem is not None and file_name_elem.text is not None else "N/A_FILENAME"

        print(
            f"  DEBUG Attachment Index: XML_Attachment_ObjID='{attachment_id_text}', XML_FileName='{file_name_text}', XML_OriginalContainerID='{original_container_id}'")

        if attachment_id_elem and file_name_elem is not None and file_name_elem.text:
            attachment_id = attachment_id_elem.text
            if original_container_id is None:
                print(
                    f"    CRITICAL WARNING: Attachment ObjID='{attachment_id}', FileName='{file_name_elem.text}' has NO 'original_container_id' in its XML <reference name='container'>. Path finding will likely FAIL for this attachment.")

            attachment_details_map[attachment_id] = {
                'original_id': attachment_id,
                'fileName': file_name_elem.text,
                'original_container_id': original_container_id
            }
        elif attachment_id_elem:
            print(
                f"    WARNING: Attachment object with XML_ID {attachment_id_elem.text} is missing 'fileName' property or fileName is empty. Skipping.")
    print(f"Indexed {len(attachment_details_map)} Attachment objects with details.")

    processed_content_items = []
    content_ids_processed = set()
    print("\n[XML PARSE - PASS 3] Processing Page, BlogPost, and CustomContentEntityObject objects...")
    for obj in root.findall('object'):
        class_name = obj.get('class')
        if class_name not in ['Page', 'BlogPost', 'CustomContentEntityObject']:
            continue

        content_id_elem = obj.find('id')
        if not content_id_elem or not content_id_elem.text:
            continue
        original_content_id = content_id_elem.text
        if original_content_id in content_ids_processed:
            continue

        status_elem = obj.find('property[@name="contentStatus"]')
        status = status_elem.text if status_elem and status_elem.text else 'current'

        if status == 'current':
            title_elem = obj.find('property[@name="title"]')
            if not title_elem or not title_elem.text:
                continue

            content_ids_processed.add(original_content_id)
            version_elem = obj.find('property[@name="version"]')
            original_parent_id_elem = obj.find('reference[@name="parent"]/id')  # For Pages
            original_parent_id = original_parent_id_elem.text if original_parent_id_elem is not None else None

            if class_name == 'Page':
                print(
                    f"  DEBUG Page Parse: Title='{title_elem.text}' (XML_ID: {original_content_id}). XML_ParentPageID: {original_parent_id}")

            api_type = "page"
            if class_name == 'BlogPost': api_type = "blogpost"

            is_internal_custom_content = obj.find('property[@name="pluginModuleKey"]') is not None and \
                                         obj.find(
                                             'property[@name="pluginModuleKey"]').text == "com.atlassian.confluence.plugins.confluence-content-property-storage:content-property"

            item_data = {
                'original_id': original_content_id, 'api_type': api_type, 'title': title_elem.text,
                'content': '<!-- Body content not found -->', 'attachments': [],
                'version': int(version_elem.text) if version_elem and version_elem.text else 1,
                'original_parent_id': original_parent_id,
                'is_internal_custom_content': is_internal_custom_content
            }

            body_content_id_ref_elem = obj.find('.//collection[@name="bodyContents"]/element[@class="BodyContent"]/id')
            if body_content_id_ref_elem and body_content_id_ref_elem.text in body_content_map:
                item_data['content'] = body_content_map[body_content_id_ref_elem.text]

            attachment_id_ref_elements = obj.findall(
                './/collection[@name="attachments"]/element[@class="Attachment"]/id')
            if attachment_id_ref_elements:
                print(
                    f"    DEBUG Content '{item_data['title']}' (XML_ID: {original_content_id}) lists {len(attachment_id_ref_elements)} attachment references in XML.")
            for att_id_ref_elem in attachment_id_ref_elements:
                att_id = att_id_ref_elem.text
                if att_id in attachment_details_map:
                    if attachment_details_map[att_id]['original_container_id'] != original_content_id:
                        print(
                            f"      WARNING: Attachment ObjID {att_id} is listed under ContentID {original_content_id}, "
                            f"but its own indexed XML_OriginalContainerID is {attachment_details_map[att_id]['original_container_id']}. This is unusual. "
                            f"Will use {original_content_id} for path finding if needed, but check XML consistency.")
                    item_data['attachments'].append(attachment_details_map[att_id])
                else:
                    print(
                        f"      WARNING: Attachment reference ID {att_id} for content '{item_data['title']}' not found in indexed attachment_details_map. Skipping this attachment reference.")
            processed_content_items.append(item_data)

    print(f"\nFound {len(processed_content_items)} current, titled content items for migration.")
    print("--- Finished XML Parsing ---")
    return processed_content_items


def get_space_key_from_parent(parent_page_id):
    if not parent_page_id: return None
    url = f"{API_BASE}/content/{parent_page_id}?expand=space"
    print(f"Fetching space key for CLI parent page ID: {parent_page_id}")
    try:
        response = requests.get(url, headers=DEFAULT_JSON_HEADERS, auth=AUTH)
        response.raise_for_status()
        space_data = response.json().get('space')
        if space_data and 'key' in space_data:
            print(f"  Target space key: {space_data['key']}")
            return space_data['key']
        print(f"  Error: Could not find space key for parent ID {parent_page_id}. Response: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"  Error fetching space key: {e}")
    return None


def create_content_in_confluence(item_data, space_key, effective_target_parent_id=None):
    url = f"{API_BASE}/content"
    payload = {
        "type": item_data['api_type'], "title": item_data['title'],
        "space": {"key": space_key},
        "body": {"storage": {"value": item_data['content'], "representation": "storage"}}
    }
    if item_data['api_type'] == "page" and effective_target_parent_id:
        payload["ancestors"] = [{"id": effective_target_parent_id}]

    parent_info = f" under TARGET parent ID '{effective_target_parent_id}'" if item_data[
                                                                                   'api_type'] == "page" and effective_target_parent_id else " (as top-level in target hierarchy or blog post)"
    print(f"  Attempting to create {item_data['api_type']}: '{item_data['title']}' in space '{space_key}'{parent_info}")

    try:
        response = requests.post(url, json=payload, headers=DEFAULT_JSON_HEADERS, auth=AUTH)
        if response.status_code == 400 and "A page with this title already exists" in response.text:
            print(
                f"    WARNING: Content '{item_data['title']}' may already exist. Skipping creation. Check Confluence. Response: {response.text[:200]}")
            return None
        response.raise_for_status()
        new_id = response.json()['id']
        print(f"    SUCCESS: Created {item_data['api_type']} '{item_data['title']}', New Confluence ID: {new_id}")
        return new_id
    except requests.exceptions.HTTPError as e:
        print(
            f"    HTTP ERROR creating content '{item_data['title']}': {e.response.status_code if e.response else 'N/A'}")
        if e.response is not None: print(f"    Response: {e.response.text}")
        raise
    except Exception as e:
        print(f"    UNEXPECTED ERROR creating content '{item_data['title']}': {e}")
        traceback.print_exc()
        raise


def list_dirs(path, indent="        "):
    """Helper to list directory contents for debugging attachment paths."""
    print(f"{indent}Attempting to list contents of: {path}")
    if not os.path.isdir(path):
        print(f"{indent}  Path does not exist or is not a directory.")
        return
    try:
        contents = os.listdir(path)
        if not contents:
            print(f"{indent}  Directory is empty.")
        else:
            print(f"{indent}  Contents:")
            for item in contents[:10]:  # Print first 10 items
                print(f"{indent}    - {item}")
            if len(contents) > 10:
                print(f"{indent}    ... and {len(contents) - 10} more items.")
    except OSError as e:
        print(f"{indent}  Error listing directory: {e}")


def find_attachment_file_on_disk(attachments_export_dir, attachment_object_id, original_filename,
                                 original_container_page_id):
    print(
        f"    DEBUG AttachmentPath: Locating file for XML_AttachObjID='{attachment_object_id}', FileName='{original_filename}', LinkedTo_XML_PageID='{original_container_page_id}'")

    if not original_container_page_id:
        print(
            f"      CRITICAL ERROR: LinkedTo_XML_PageID is missing for attachment '{original_filename}'. Cannot determine attachment directory path. Skipping this attachment.")
        return None

    page_attachment_dir = os.path.join(attachments_export_dir, str(original_container_page_id))
    attachment_object_dir_base = os.path.join(page_attachment_dir, str(attachment_object_id))

    paths_to_try = []
    paths_to_try.append(os.path.join(attachment_object_dir_base, original_filename))

    version_dir_glob_pattern = os.path.join(attachment_object_dir_base, "*", original_filename)

    for p_idx, path_candidate in enumerate(paths_to_try):
        print(f"      Attempting path {p_idx + 1} (direct): {path_candidate}")
        if os.path.isfile(path_candidate):
            print(f"        FOUND file at: {path_candidate}")
            return path_candidate

    print(f"      Attempting path with version glob: {version_dir_glob_pattern}")
    glob_matches = glob.glob(version_dir_glob_pattern)
    if glob_matches:
        glob_matches.sort(key=lambda x: os.path.basename(os.path.dirname(x)),
                          reverse=True)  # Try to get latest version by dirname
        print(f"        FOUND {len(glob_matches)} match(es) via glob. Using: {glob_matches[0]}")
        return glob_matches[0]

    print(
        f"      WARNING: Attachment file '{original_filename}' (XML_AttachObjID: {attachment_object_id}) for XML_PageID {original_container_page_id} NOT FOUND.")
    print(f"      Expected Page Attachment Dir (should exist): {page_attachment_dir}")
    list_dirs(page_attachment_dir)
    print(f"      Expected Attachment Object Dir (should exist under page dir): {attachment_object_dir_base}")
    list_dirs(attachment_object_dir_base)

    return None


def upload_attachments_to_content(newly_created_content_id, attachments_data_for_item, attachments_export_dir):
    if not attachments_data_for_item:        return
    print(
        f"  Processing {len(attachments_data_for_item)} attachments for new Confluence Content ID {newly_created_content_id}...")
    for att_data in attachments_data_for_item:
        xml_attachment_object_id = att_data['original_id']
        xml_filename = att_data['fileName']
        xml_original_container_page_id = att_data.get('original_container_id')

        print(
            f"    Trying to find & upload: XML_Attachment_ObjID='{xml_attachment_object_id}', FileName='{xml_filename}', OriginallyOn_XML_PageID='{xml_original_container_page_id}'")

        file_path_on_disk = find_attachment_file_on_disk(
            attachments_export_dir, xml_attachment_object_id, xml_filename, xml_original_container_page_id
        )
        if not file_path_on_disk: continue

        upload_url = f"{API_BASE}/content/{newly_created_content_id}/child/attachment"
        upload_headers = {"X-Atlassian-Token": "nocheck", "Accept": "application/json"}
        content_type, _ = mimetypes.guess_type(xml_filename);
        content_type = content_type or 'application/octet-stream'

        try:
            with open(file_path_on_disk, 'rb') as f_attach:
                files_payload = {'file': (xml_filename, f_attach, content_type)}
                print(f"      Uploading '{xml_filename}' from local: '{file_path_on_disk}'")
                response = requests.post(upload_url, headers=upload_headers, auth=AUTH, files=files_payload)
            if 200 <= response.status_code < 300:
                new_aid = "N/A";
                try:
                    new_aid = response.json().get('results', [{}])[0].get('id', 'N/A')
                except:
                    pass
                print(f"        SUCCESS: Uploaded '{xml_filename}' (New Confluence Attach ID: {new_aid})")
            else:
                print(
                    f"        FAILED to upload '{xml_filename}'. Status: {response.status_code}, Response: {response.text[:300]}")
        except Exception as e:
            print(f"        ERROR during upload of '{xml_filename}': {e}");
            traceback.print_exc()


def main(export_root_dir, cli_target_parent_page_id_str):
    if not CONFLUENCE_USERNAME or not CONFLUENCE_PASSWORD:
        print("Error: Credentials not set.");
        return

    xml_file_path = os.path.join(export_root_dir, "entities.xml")
    attachments_base_dir = os.path.join(export_root_dir, "attachments")
    if not os.path.exists(xml_file_path): print(f"Error: entities.xml not found in: '{export_root_dir}'"); return
    attachments_dir_exists = os.path.isdir(attachments_base_dir)
    if not attachments_dir_exists: print(
        f"Warning: Attachments dir '{attachments_base_dir}' not found. Will not upload attachments.")

    target_space_key = get_space_key_from_parent(cli_target_parent_page_id_str)
    if not target_space_key: print(
        f"Error: No space key from CLI parent ID '{cli_target_parent_page_id_str}'. Aborting."); return

    content_items_to_migrate = parse_xml(xml_file_path)
    if not content_items_to_migrate: print("No content items to migrate."); return

    print(
        f"\n--- Starting Migration of {len(content_items_to_migrate)} Content Items to Space '{target_space_key}' ---")
    original_xml_id_to_new_confluence_id_map = {}

    for i, item_data in enumerate(content_items_to_migrate):
        print(
            f"\n--- Processing Item {i + 1}/{len(content_items_to_migrate)} (XML Type: {item_data['api_type'].upper()}) ---")
        print(
            f"Title: '{item_data['title']}' (XML_ID: {item_data['original_id']}, XML_ParentPageID: {item_data.get('original_parent_id', 'N/A')})")

        effective_target_parent_id_in_confluence = None
        if item_data['api_type'] == 'page':  # Only standard pages have explicit 'ancestors'
            xml_parent_id_of_this_item = item_data.get('original_parent_id')

            if xml_parent_id_of_this_item:
                if xml_parent_id_of_this_item in original_xml_id_to_new_confluence_id_map:
                    effective_target_parent_id_in_confluence = original_xml_id_to_new_confluence_id_map[
                        xml_parent_id_of_this_item]
                    print(
                        f"  PARENTING: XML parent '{xml_parent_id_of_this_item}' was already created. New Target Parent Confluence ID: {effective_target_parent_id_in_confluence}")
                else:
                    effective_target_parent_id_in_confluence = cli_target_parent_page_id_str
                    print(
                        f"  PARENTING: XML parent '{xml_parent_id_of_this_item}' NOT YET PROCESSED in this run OR not a 'Page' type. Defaulting to CLI Parent ID: {effective_target_parent_id_in_confluence}")
            else:
                effective_target_parent_id_in_confluence = cli_target_parent_page_id_str
                print(
                    f"  PARENTING: Item is a TOP-LEVEL page from XML export. Target Parent is CLI Parent ID: {effective_target_parent_id_in_confluence}")
        else:
            print(
                f"  PARENTING: Item is '{item_data['api_type']}', does not use explicit Confluence parent page structure in the same way.")

        if item_data['is_internal_custom_content']:
            print(
                f"  INFO: Item '{item_data['title']}' is internal custom content. Will be migrated as a standard page; may appear as raw data.")

        try:
            newly_created_confluence_id = create_content_in_confluence(
                item_data, target_space_key, effective_target_parent_id_in_confluence
            )
            if newly_created_confluence_id:
                original_xml_id_to_new_confluence_id_map[item_data['original_id']] = newly_created_confluence_id
                if item_data['attachments'] and attachments_dir_exists:
                    upload_attachments_to_content(newly_created_confluence_id, item_data['attachments'],
                                                  attachments_base_dir)
        except Exception:
            print(f"  CRITICAL ERROR processing item '{item_data['title']}'. Details above. Item not fully migrated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Confluence content from XML export.",
                                     formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("export_dir",
                        help="Path to Confluence export directory (must contain entities.xml and attachments/).")
    parser.add_argument("cli_parent_id",
                        help="Numeric ID of the TARGET Confluence page (in http://localhost:8090) under which the TOP-LEVEL pages from the export will be created.")
    args = parser.parse_args()

    print(f"--- Confluence XML Migration Script ---")
    print(f"Target Confluence URL: {CONFLUENCE_URL}")
    print(f"Export Directory: {args.export_dir}")
    print(f"CLI Target Parent Page ID (for top-level imported pages): {args.cli_parent_id}")

    if not CONFLUENCE_USERNAME or not CONFLUENCE_PASSWORD:
        print("\nERROR: CONFLUENCE_USERNAME or CONFLUENCE_PASSWORD not set in .env or environment variables.")
    else:
        main(args.export_dir, args.cli_parent_id)
    print(f"\n--- Migration Process Finished ---")
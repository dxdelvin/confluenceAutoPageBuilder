<img width="1900" height="853" alt="image" src="https://github.com/user-attachments/assets/5ff65382-0835-498f-949b-472e0cdc981c" />

<img width="1882" height="840" alt="image" src="https://github.com/user-attachments/assets/54355732-568f-419e-a039-de2c23c0dadd" />

A lightweight automation tool to create, update, and manage Confluence pages directly from a simple UI.
This tool streamlines Confluence documentation workflows by allowing quick content publishing, attachments upload, and page management — without needing to navigate the Confluence editor manually.


## 🛠️ How It Works

Pip install streamlit requests
streamlit run confluence_uploader.py

1. **Configure Confluence**
   - Enter your Confluence URL, space key, and PAT.
   
2. **Prepare Content**
   - Add page title (optional).
   - Paste content in Confluence XML storage format.
   - Optionally set a parent page ID for hierarchy.
   
3. **Add Attachments (Optional)**
   - Upload relevant files to attach to the page.
   
4. **Publish Page**
   - Click **Create Page & Upload Attachments**.
   - Monitor results in the **Operation Logs** section.

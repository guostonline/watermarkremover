import os
import re

APP_PY_PATH = "app.py"

with open(APP_PY_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update Flask init
content = content.replace(
    'app = Flask(__name__, template_folder="templates", static_folder="static")',
    'app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "frontend", "dist"), static_url_path="")'
)

# 2. Remove all those HTML routes
routes_to_remove = re.compile(
    r'@app\.route\("/"\)\n.*?\n\n'
    r'.*?'
    r'@app\.route\("/site\.webmanifest"\)\n.*?\}\)\n',
    re.DOTALL
)
# Add catch-all React serve route instead
catch_all_route = """@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_file(os.path.join(app.static_folder, path))
    else:
        return send_file(os.path.join(app.static_folder, "index.html"))
"""
content = routes_to_remove.sub(catch_all_route, content)

# 3. Remove admin HTML route
admin_route_to_remove = re.compile(
    r'@app\.route\("/admin"\)\ndef admin_dashboard\(\):\n\s+return render_template\("admin\.html"\)\n',
    re.DOTALL
)
content = admin_route_to_remove.sub("", content)

# 4. Modify handle_remove return
handle_remove_old = """        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"no_watermark_{f.filename}",
            mimetype="application/pdf",
        )"""

handle_remove_new = """        with open(output_path, "rb") as out_f:
            b64_data = base64.b64encode(out_f.read()).decode("utf-8")
        return jsonify({
            "success": True,
            "filename": f"no_watermark_{f.filename}",
            "data": b64_data
        })"""
content = content.replace(handle_remove_old, handle_remove_new)

# 5. Modify handle_process return
handle_process_old = """        return send_file(
            output_path,
            as_attachment=True,
            download_name=dl_name,
            mimetype="application/pdf",
        )"""

handle_process_new = """        with open(output_path, "rb") as out_f:
            b64_data = base64.b64encode(out_f.read()).decode("utf-8")
        return jsonify({
            "success": True,
            "filename": dl_name,
            "data": b64_data
        })"""
content = content.replace(handle_process_old, handle_process_new)

# 6. Modify handle_stamp return
handle_stamp_old = """        return send_file(
            output_path,
            as_attachment=True,
            download_name=f"stamped_{pdf_file.filename}",
            mimetype="application/pdf",
        )"""

handle_stamp_new = """        with open(output_path, "rb") as out_f:
            b64_data = base64.b64encode(out_f.read()).decode("utf-8")
        return jsonify({
            "success": True,
            "filename": f"stamped_{pdf_file.filename}",
            "data": b64_data
        })"""
content = content.replace(handle_stamp_old, handle_stamp_new)


with open(APP_PY_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print("Done refactoring app.py")

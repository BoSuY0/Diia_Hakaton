import subprocess
import sys
import json
import shutil
from pathlib import Path
from backend.infra.config.settings import settings

def run_command(args):
    cmd = [sys.executable, "manage_content.py"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"CMD: {' '.join(cmd)}")
    print(f"STDOUT: {result.stdout.strip()}")
    if result.stderr:
        print(f"STDERR: {result.stderr.strip()}")
    return result.returncode == 0

def verify():
    print("=== Starting CLI Verification ===")
    
    test_cat_id = "test_cli_category"
    test_cat_label = "Тестова Категорія"
    
    # Cleanup before start
    index_path = settings.meta_categories_root / "categories_index.json"
    cat_file = settings.meta_categories_root / f"{test_cat_id}.json"
    
    # 1. Test Add Category
    print("\n--- Test 1: Add Category ---")
    if run_command(["add-category", "--id", test_cat_id, "--label", test_cat_label]):
        if cat_file.exists():
            print("[OK] Category file created.")
        else:
            print("[ERROR] Category file NOT found.")
            return
    else:
        print("[ERROR] Command failed.")
        return

    # 2. Test Add Template
    print("\n--- Test 2: Add Template ---")
    if run_command(["add-template", "--category", test_cat_id, "--id", "test_tmpl", "--name", "Test Template"]):
        with cat_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if any(t["id"] == "test_tmpl" for t in data.get("templates", [])):
                print("[OK] Template added to JSON.")
            else:
                print("[ERROR] Template NOT found in JSON.")
    else:
        print("[ERROR] Command failed.")

    # 3. Test Add Field
    print("\n--- Test 3: Add Field ---")
    if run_command(["add-field", "--category", test_cat_id, "--field", "test_field", "--label", "Test Label", "--required"]):
        with cat_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            if any(f["field"] == "test_field" for f in data.get("contract_fields", [])):
                print("[OK] Field added to JSON.")
            else:
                print("[ERROR] Field NOT found in JSON.")
    else:
        print("[ERROR] Command failed.")

    # Cleanup
    print("\n--- Cleanup ---")
    # Remove from index
    if index_path.exists():
        with index_path.open("r", encoding="utf-8") as f:
            idx_data = json.load(f)
        idx_data["categories"] = [c for c in idx_data["categories"] if c["id"] != test_cat_id]
        with index_path.open("w", encoding="utf-8") as f:
            json.dump(idx_data, f, indent=2, ensure_ascii=False)
        print("Cleaned index.")
    
    # Remove file
    if cat_file.exists():
        cat_file.unlink()
        print("Removed category file.")
    
    if cat_file.with_suffix(".json.bak").exists():
        cat_file.with_suffix(".json.bak").unlink()
        print("Removed backup file.")

    print("\n=== Verification Finished ===")

if __name__ == "__main__":
    verify()

import subprocess
import sys
import json
from pathlib import Path
from src.common.config import settings

def run_command(args):
    cmd = [sys.executable, "manage_content.py"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"[ERROR] Command failed: {' '.join(cmd)}")
        print(result.stderr)
        return False
    return True

def demo():
    print("=== Demo: Registering 'Lease Flat' Document ===")
    
    # 1. Create a new category for this demo
    cat_id = "demo_lease_living"
    cat_label = "Демо: Оренда Житла"
    
    print(f"\n1. Creating category '{cat_label}'...")
    if not run_command(["add-category", "--id", cat_id, "--label", cat_label]):
        return

    # 2. Add the template pointing to the real file
    # Note: We use the filename 'lease_flat.docx' as requested
    tmpl_id = "demo_lease_flat"
    tmpl_name = "Договір оренди квартири (Демо)"
    tmpl_file = "lease_flat.docx"
    
    print(f"\n2. Adding template '{tmpl_name}' pointing to '{tmpl_file}'...")
    if not run_command(["add-template", "--category", cat_id, "--id", tmpl_id, "--name", tmpl_name, "--file", tmpl_file]):
        return

    # 3. Add some fields that match the real document structure (based on lease_living.json)
    print("\n3. Adding contract fields...")
    fields = [
        ("object_address", "Адреса житла", True),
        ("rent_price_month", "Сума оренди (грн/міс)", True),
        ("start_date", "Дата початку", True)
    ]
    
    for field, label, required in fields:
        args = ["add-field", "--category", cat_id, "--field", field, "--label", label]
        if required:
            args.append("--required")
        run_command(args)

    # 4. Show the result
    print("\n=== Resulting JSON Structure ===")
    meta_path = settings.meta_categories_root / f"{cat_id}.json"
    if meta_path.exists():
        with meta_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            print(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        print("[ERROR] Metadata file not found!")

    # Cleanup
    print("\n=== Cleanup ===")
    # Remove from index
    index_path = settings.meta_categories_root / "categories_index.json"
    if index_path.exists():
        with index_path.open("r", encoding="utf-8") as f:
            idx_data = json.load(f)
        idx_data["categories"] = [c for c in idx_data["categories"] if c["id"] != cat_id]
        with index_path.open("w", encoding="utf-8") as f:
            json.dump(idx_data, f, indent=2, ensure_ascii=False)
        print("Removed from index.")

    # Remove file
    if meta_path.exists():
        meta_path.unlink()
        print("Removed metadata file.")
    if meta_path.with_suffix(".json.bak").exists():
        meta_path.with_suffix(".json.bak").unlink()

if __name__ == "__main__":
    demo()

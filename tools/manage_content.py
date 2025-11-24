import argparse
import sys
from backend.domain.content.manager import ContentManager
from backend.shared.logging import setup_logging

def main():
    setup_logging()
    manager = ContentManager()

    parser = argparse.ArgumentParser(description="Developer CLI for managing bot content (categories, templates).")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: add-category
    cat_parser = subparsers.add_parser("add-category", help="Create a new category")
    cat_parser.add_argument("--id", required=True, help="Category ID (slug), e.g. 'auto_lease'")
    cat_parser.add_argument("--label", required=True, help="Human readable label, e.g. 'Оренда авто'")

    # Command: add-template
    tmpl_parser = subparsers.add_parser("add-template", help="Add a template to a category")
    tmpl_parser.add_argument("--category", required=True, help="Category ID to add to")
    tmpl_parser.add_argument("--id", required=True, help="Template ID (slug)")
    tmpl_parser.add_argument("--name", required=True, help="Template name")
    tmpl_parser.add_argument("--file", help="Filename (optional, defaults to id.docx)")

    # Command: add-field
    field_parser = subparsers.add_parser("add-field", help="Add a contract field to a category")
    field_parser.add_argument("--category", required=True, help="Category ID")
    field_parser.add_argument("--field", required=True, help="Field name (slug)")
    field_parser.add_argument("--label", required=True, help="Field label")
    field_parser.add_argument("--required", action="store_true", help="Is field required?")

    args = parser.parse_args()

    if args.command == "add-category":
        try:
            manager.add_category(args.id, args.label)
            print(f"[OK] Category '{args.id}' created successfully.")
        except Exception as e:
            print(f"[ERROR] Error: {e}")

    elif args.command == "add-template":
        try:
            manager.add_template(args.category, args.id, args.name, args.file)
            print(f"[OK] Template '{args.id}' added to category '{args.category}'.")
        except Exception as e:
            print(f"[ERROR] Error: {e}")

    elif args.command == "add-field":
        try:
            manager.add_field(args.category, args.field, args.label, args.required)
            print(f"[OK] Field '{args.field}' added to category '{args.category}'.")
        except Exception as e:
            print(f"[ERROR] Error: {e}")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()

"""Developer CLI for managing bot content (categories, templates, fields)."""
import argparse

from backend.domain.content.manager import ContentManager
from backend.shared.logging import setup_logging


def main() -> None:
    """Main entry point for content management CLI."""
    setup_logging()
    manager = ContentManager()

    parser = argparse.ArgumentParser(
        description="Developer CLI for managing bot content.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: add-category
    cat_parser = subparsers.add_parser("add-category", help="Create a new category")
    cat_parser.add_argument("--id", required=True, help="Category ID (slug), e.g. 'auto_lease'")
    cat_parser.add_argument(
        "--label", required=True, help="Human readable label",
    )

    # Command: add-template
    tmpl_parser = subparsers.add_parser("add-template", help="Add a template to a category")
    tmpl_parser.add_argument("--category", required=True, help="Category ID to add to")
    tmpl_parser.add_argument("--id", required=True, help="Template ID (slug)")
    tmpl_parser.add_argument("--name", required=True, help="Template name")
    tmpl_parser.add_argument("--file", help="Filename (optional, defaults to id.docx)")

    # Command: add-role
    role_parser = subparsers.add_parser("add-role", help="Add a role to a category")
    role_parser.add_argument("--category", required=True, help="Category ID")
    role_parser.add_argument("--id", required=True, help="Role ID (slug), e.g. 'lessor', 'buyer'")
    role_parser.add_argument("--label", required=True, help="Role label for display")
    role_parser.add_argument(
        "--allowed-types",
        help="Comma-separated allowed person types (default: all)",
    )
    role_parser.add_argument(
        "--default-type",
        help="Default person type for this role",
    )

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
        except (OSError, ValueError, KeyError) as e:
            print(f"[ERROR] Error: {e}")

    elif args.command == "add-template":
        try:
            manager.add_template(args.category, args.id, args.name, args.file)
            print(f"[OK] Template '{args.id}' added to category '{args.category}'.")
        except (OSError, ValueError, KeyError) as e:
            print(f"[ERROR] Error: {e}")

    elif args.command == "add-role":
        try:
            allowed_types = None
            if args.allowed_types:
                allowed_types = [t.strip() for t in args.allowed_types.split(",")]
            manager.add_role(
                args.category,
                args.id,
                args.label,
                allowed_person_types=allowed_types,
                default_person_type=args.default_type,
            )
            print(f"[OK] Role '{args.id}' added to category '{args.category}'.")
        except (OSError, ValueError, KeyError) as e:
            print(f"[ERROR] Error: {e}")

    elif args.command == "add-field":
        try:
            manager.add_field(args.category, args.field, args.label, args.required)
            print(f"[OK] Field '{args.field}' added to category '{args.category}'.")
        except (OSError, ValueError, KeyError) as e:
            print(f"[ERROR] Error: {e}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

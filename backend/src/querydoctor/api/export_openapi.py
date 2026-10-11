"""Print the OpenAPI document. Feeds frontend type generation (pnpm gen:api)."""

import json
import sys

from querydoctor.api.main import create_app


def main() -> None:
    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

import uvicorn

from mock_immich.app import create_mock_app


def main() -> None:
    uvicorn.run(create_mock_app(), host="0.0.0.0", port=3001)


if __name__ == "__main__":
    main()

import uvicorn
from utils.config_handler import enterprise_conf


def main():
    api_conf = enterprise_conf.get("api", {})
    uvicorn.run(
        "enterprise.api.app:app",
        host=api_conf.get("host", "0.0.0.0"),
        port=int(api_conf.get("port", 8000)),
        reload=False,
    )


if __name__ == "__main__":
    main()

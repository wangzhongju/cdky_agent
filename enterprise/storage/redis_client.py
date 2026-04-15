import redis
from utils.config_handler import enterprise_conf


def _redis_url() -> str:
    redis_url = enterprise_conf.get("infra", {}).get("redis_url", "")
    if not redis_url:
        raise RuntimeError("REDIS_URL 未配置，无法启动企业级 A2A")
    return redis_url


def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(_redis_url(), decode_responses=True)

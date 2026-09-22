from abc import ABC, abstractmethod
from typing import Any


class Cache(ABC):
    """
    Abstract base class for all cache implementations.
    """

    @abstractmethod
    def get(self, key: str) -> Any:
        """
        Retrieve a value from the cache by key.
        :param key: The key to retrieve.
        :return: The cached value, or None if not found.
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """
        Set a value in the cache with the given key.
        :param key: The key to set.
        :param value: The value to cache.
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """
        Delete a value from the cache by key.
        :param key: The key to delete.
        """
        pass

    @abstractmethod
    def exists(self, key: str) -> bool:
        """
        Check if a key exists in the cache.
        :param key: The key to check.
        :return: True if key exists, False otherwise.
        """
        pass
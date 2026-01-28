from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Generic, TypeVar

K = TypeVar('K', bound=Hashable)
V = TypeVar('V')


class SLRUCache(Generic[K, V]):
    """
    Segmented Least Recently Used (SLRU) cache.
    """
    def __init__(
        self,
        function: Callable[[], V],
        total_capacity: int,
        prob_capacity: int
    ) -> None:
        """
        Initialise cache.
        """
        self.function = function

        if total_capacity <= 0:
            raise ValueError('Capacity must be larger than 0.')
        if prob_capacity >= total_capacity:
            raise ValueError(
                'Probationary capacity must be lower than the total.'
            )
        self.total_capacity = total_capacity
        self.prob_capacity = prob_capacity
        self.prot_capacity = total_capacity - prob_capacity

        self.probationary: OrderedDict[K, V] = OrderedDict()
        self.protected: OrderedDict[K, V] = OrderedDict()

    def __getitem__(self, key: K) -> tuple[V, bool]:
        """
        Lookup an item in the cache, includes a
        `True` for a cache hit and `False` if it misses.
        """
        # Hit in protected
        if key in self.protected:
            self.protected.move_to_end(key)
            return self.protected[key], True

        # Hit in probationary
        if key in self.probationary:
            value = self.probationary.pop(key)
            self._promote(key, value)
            return value, True

        # Miss and assign
        return self._insert_missed(key), False

    def _promote(self, key: K, value: V) -> None:
        """
        Promote an item from the probationary cache.
        """
        # Ensure protected segment has room
        if len(self.protected) >= self.prot_capacity:
            # Demote LRU from protected to probationary
            demoted_key, demoted_value = self.protected.popitem(last=False)
            self.probationary[demoted_key] = demoted_value

        self.protected[key] = value

    def _insert_missed(self, key: K) -> V:
        """
        Insert a missed value and return the function result.
        """
        # If the probationary cache is full, evict LRU from probationary
        if len(self.probationary) >= self.prob_capacity:
            _, evicted_code = self.probationary.popitem(last=False)
            value = evicted_code
        else:
            value = self.function()

        # Insert value at MRU end
        self.probationary[key] = value
        return value

    def clear(self) -> None:
        """
        Clear cache.
        """
        self.probationary.clear()
        self.protected.clear()

    def debug_state(self) -> dict[str, OrderedDict[K, V]]:
        """
        Get both cache partitions as a copy.
        """
        return {
            'probationary': self.probationary.copy(),
            'protected': self.protected.copy(),
        }

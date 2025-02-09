def get_timeout(self, key: str) -> float:
        if not self._history[key]:
            return self._min
        avg = statistics.mean(self._history[key])
        return min(max(avg, self._min), self._max)
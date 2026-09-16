"""Native local-table adapter used by the C8 reference semantic layer."""

from __future__ import annotations

from dataclasses import dataclass

from edge63_C8_native_bridge import NativeRecord, NativeTable


@dataclass(frozen=True)
class NativeSemanticIndex:
    """In-memory inverted index over one native geometry table."""

    table: NativeTable
    contains_by_offset: dict[int, int]

    @classmethod
    def build(cls, table: NativeTable) -> "NativeSemanticIndex":
        contains: dict[int, int] = {}
        for row in table.records:
            bit = 1 << row.behavior_id
            for offset in row.private:
                contains[offset] = contains.get(offset, 0) | bit
        return cls(table=table, contains_by_offset=contains)

    def query_bits(self, occupied: frozenset[int], shift: int,
                   middle_min: int, middle_max: int) -> int:
        result = (1 << len(self.table.records)) - 1
        blocked = 0
        for offset in occupied:
            blocked |= self.contains_by_offset.get(offset, 0)
        result &= ~blocked
        for row in self.table.records:
            bit = 1 << row.behavior_id
            low = min(middle_min, row.min_value + shift)
            high = max(middle_max, row.max_value + shift)
            if high - low > 63:
                result &= ~bit
        return result

    def records_for_bits(self, bits: int) -> tuple[NativeRecord, ...]:
        result = []
        remaining = int(bits)
        while remaining:
            low = remaining & -remaining
            index = low.bit_length() - 1
            result.append(self.table.records[index])
            remaining ^= low
        return tuple(result)

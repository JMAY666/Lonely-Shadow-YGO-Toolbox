"""Bounded, consistency-checked reads shared by the verified Unity adapters."""
import struct


class CheckedMemory:
    def read(self, address, size, guard=True):
        if not 0x10000 <= address < 0x7fffffffffff or not 0 <= size <= 8192: self.fail()
        data = self.memory.read(address, size)
        if len(data) != size: self.fail()
        if guard:
            key = (address, size)
            if key in self.guards and self.guards[key] != data: self.fail()
            self.guards[key] = data
        return data

    def integer(self, address):
        return struct.unpack('<i', self.read(address, 4))[0]

    def pointer(self, address, nullable=False, aligned=True):
        value = struct.unpack('<Q', self.read(address, 8))[0]
        if nullable and value == 0: return 0
        if not 0x10000 <= value < 0x7fffffffffff or (aligned and value % 8): self.fail()
        return value

    def boolean(self, address):
        value = self.read(address, 1)[0]
        if value not in (0, 1): self.fail()
        return bool(value)

    def cstring(self, address):
        data = self.read(address, 96, guard=False)
        if b'\0' not in data: self.fail()
        data = self.read(address, data.index(0) + 1)
        try: return data[:-1].decode('utf-8')
        except UnicodeError: self.fail()

    def string(self, address):
        if not address: return ''
        size = self.integer(address + 16)
        if not 0 <= size <= 128: self.fail()
        try: return self.read(address + 20, size * 2).decode('utf-16-le')
        except UnicodeError: self.fail()

    def verify(self):
        if any(self.memory.read(a, size) != value for (a, size), value in self.guards.items()): self.fail()

    def sequence(self, obj, element='Q', limit=256, prefix=None):
        """Verified List<T> header, capacity, contents and version, guarded twice."""
        header = self.read(obj + 16, 16)
        array, count, _ = struct.unpack('<Qii', header)
        if not 0 <= count <= limit or array < 0x10000 or array % 8: self.fail()
        capacity = struct.unpack('<Q', self.read(array + 24, 8))[0]
        if not count <= capacity <= max(limit * 2, 4): self.fail()
        taken = count if prefix is None else min(count, prefix)
        raw = self.read(array + 32, taken * struct.calcsize(element))
        return [value for (value,) in struct.iter_unpack('<' + element, raw)]

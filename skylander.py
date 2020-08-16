class Skylander(object):
    def __init__(self, path):
        self.path = path

    @property
    def path(self):
        return self._path

    @path.setter
    def path(self, path: str):
        with open(path, 'rb') as fp:
            self._data = fp.read()
        self._path = path

    @property
    def data(self):
        return self._data

    def readBlock(self, index: int):
        offset = index * 0x10
        length = offset + 0x10
        return self._data[offset:length]

    def writeBlock(self, index: int, block: bytes):
        offset = index * 0x10
        length = offset + len(block)
        self._data = self._data[0:offset] + block + self._data[length:]

    def save(self):
        with open(self.path, 'wb') as fp:
            fp.write(self._data)


class Slot(object):
    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, status: bool):
        self._active = status

    @property
    def skylander(self):
        return self._skylander

    @skylander.setter
    def skylander(self, skylander: Skylander):
        self._skylander = skylander

    def __repr__(self):
        return "<Slot active=%d Skylander=%s>" % (self.active, self.skylander)

    def __init__(self, skylander: Skylander = None, active=False):
        self.skylander = skylander
        self.active = active

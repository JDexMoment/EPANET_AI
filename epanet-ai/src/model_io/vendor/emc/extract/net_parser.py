"""
Надёжный парсер бинарных .NET файлов EPANET.
Правильно декодирует 10-байтные числа Delphi Extended.
"""

import struct
import math
import traceback
from pathlib import Path
from typing import Dict, List, Tuple


class NetParser:
    SUPPORTED_EXTENSIONS = {'.net'}

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self._sections: Dict[str, List[str]] = {}
        self._section_order: List[str] = []
        self._preamble: List[str] = []
        self._data: bytes = b''

    @staticmethod
    def is_supported(filepath: str) -> bool:
        return Path(filepath).suffix.lower() in NetParser.SUPPORTED_EXTENSIONS

    def read(self) -> Tuple[Dict[str, List[str]], List[str]]:
        if not self.filepath.exists():
            raise FileNotFoundError(f"Файл не найден: {self.filepath}")

        with open(self.filepath, 'rb') as f:
            self._data = f.read()

        if b'<EPANET2>' not in self._data[:50]:
            raise ValueError("Файл не содержит маркер <EPANET2>")

        self._sections.clear()
        self._section_order.clear()
        self._preamble.clear()

        try:
            tokens = self._tokenize()
            self._parse_elements(tokens)
        except Exception as e:
            # Выводим полную ошибку с номером строки!
            error_trace = traceback.format_exc()
            raise RuntimeError(f"Сбой парсера .NET:\n{error_trace}")

        self._preamble.append(f"; Очищено и импортировано из .NET: {self.filepath.name}")
        return self._sections, self._section_order

    def get_preamble(self) -> List[str]:
        return list(self._preamble)

    def _add_section(self, name: str, lines: List[str]):
        if not lines:
            return
        if name not in self._sections:
            self._sections[name] = []
            self._section_order.append(name)
        self._sections[name].extend(lines)

    @staticmethod
    def _decode_extended(data: bytes, offset: int) -> float:
        if offset + 10 > len(data): return 0.0
        mantissa_bytes = data[offset : offset + 8]
        exp_bytes = data[offset + 8 : offset + 10]

        mantissa = struct.unpack('<Q', mantissa_bytes)[0]
        exp_sign = struct.unpack('<H', exp_bytes)[0]

        sign = -1.0 if (exp_sign & 0x8000) else 1.0
        exponent = exp_sign & 0x7FFF

        if exponent == 0 and mantissa == 0:
            return 0.0

        m_float = mantissa / float(1 << 63)
        try:
            return sign * m_float * math.pow(2.0, exponent - 16383)
        except OverflowError:
            return 0.0

    def _tokenize(self) -> List[Dict]:
        tokens = []
        pos = 0
        data_len = len(self._data)

        while pos < data_len:
            byte = self._data[pos]

            if byte == 0x06:
                if pos + 1 >= data_len: break
                slen = self._data[pos + 1]
                end = pos + 2 + slen
                if end <= data_len:
                    raw = self._data[pos + 2:end]
                    try:
                        text = raw.decode('utf-8', errors='ignore').strip()
                        tokens.append({'type': 'STR', 'val': text})
                    except:
                        tokens.append({'type': 'STR', 'val': ""})
                pos = end
                continue

            if byte == 0x05:
                if pos + 11 <= data_len:
                    val = self._decode_extended(self._data, pos + 1)
                    tokens.append({'type': 'DBL', 'val': val})
                pos += 11
                continue

            if byte == 0x14:
                if pos + 1 >= data_len: break
                slen = self._data[pos + 1]
                pos = pos + 2 + slen
                continue

            if byte in (0x02, 0x03):
                pos += 2
                continue

            pos += 1

        return tokens

    @staticmethod
    def _is_num(val: str) -> bool:
        if not val: return False
        try:
            float(val.replace(',', '.'))
            return True
        except ValueError:
            return False

    def _parse_elements(self, tokens: List[Dict]):
        options, patterns, curves, junctions = [], [], [], []
        reservoirs, tanks, pipes, pumps = [], [], [], []
        valves, status, coordinates = [], [], []

        i = 0
        n = len(tokens)
        current_type = 'OPTIONS'

        while i < n:
            token = tokens[i]
            typ = token['type']
            val = token['val']

            if typ != 'STR' or not val:
                i += 1
                continue

            if current_type == 'OPTIONS':
                if val in ('CMH', 'LPS', 'GPM', 'CFS', 'MGD', 'IMGD', 'AFD', 'CMD', 'LPM', 'MLD'):
                    options.append(f"Units\t{val}")
                elif val in ('H-W', 'D-W', 'C-M'):
                    options.append(f"Headloss\t{val}")
                elif val.startswith('M') and val[1:].isdigit():
                    current_type = 'PATTERNS'
                    continue
                i += 1
                continue

            if current_type == 'PATTERNS':
                if val.startswith('M') and val[1:].isdigit():
                    pat_id = val
                    mults = []
                    i += 1
                    while i < n and tokens[i]['type'] == 'STR' and self._is_num(tokens[i]['val']):
                        mults.append(tokens[i]['val'])
                        i += 1
                    for k in range(0, len(mults), 6):
                        chunk = mults[k:k+6]
                        patterns.append(f"{pat_id}\t" + "\t".join(chunk))
                    continue
                elif val.startswith('K') and val[1:].isdigit():
                    current_type = 'CURVES'
                    continue
                elif val.startswith('J') and val[1:].isdigit():
                    current_type = 'NODES'
                    continue
                i += 1
                continue

            if current_type == 'CURVES':
                if val.startswith('K') and val[1:].isdigit():
                    cur_id = val
                    pts = []
                    i += 1
                    while i < n and tokens[i]['type'] == 'STR' and self._is_num(tokens[i]['val']):
                        pts.append(tokens[i]['val'])
                        i += 1
                    for k in range(0, len(pts), 2):
                        if k + 1 < len(pts):
                            curves.append(f"{cur_id}\t{pts[k]}\t{pts[k+1]}")
                    continue
                elif val.startswith('J') and val[1:].isdigit():
                    current_type = 'NODES'
                    continue
                i += 1
                continue

            if current_type == 'NODES':
                if val.startswith('P') and val[1:].isdigit():
                    current_type = 'LINKS'
                    continue

                if (val.startswith('J') or val.startswith('S') or val.startswith('T')) and val[1:].isdigit():
                    node_id = val
                    node_type = val[0]

                    x_coord = None
                    y_coord = None
                    search_idx = i + 1

                    while search_idx < n and search_idx < i + 15:
                        t_typ = tokens[search_idx]['type']
                        t_val = tokens[search_idx]['val']
                        if t_typ == 'DBL':
                            if x_coord is None:
                                x_coord = t_val
                            elif y_coord is None:
                                y_coord = t_val
                                break
                        elif t_typ == 'STR':
                            break
                        search_idx += 1

                    if x_coord is not None and y_coord is not None:
                        coordinates.append(f"{node_id}\t{x_coord:.4f}\t{y_coord:.4f}")

                    i += 1
                    nums = []
                    pat = ""
                    while i < n:
                        t_typ = tokens[i]['type']
                        t_val = tokens[i]['val']
                        if t_typ != 'STR':
                            i += 1
                            continue

                        if t_val in ("CONCEN", "Mixed", "2-COMP", "FIFO", "LIFO"):
                            i += 1
                            break
                        if (t_val.startswith('J') or t_val.startswith('S') or
                            t_val.startswith('T') or t_val.startswith('P')) and t_val[1:].isdigit():
                            break

                        if t_val.startswith('M') and t_val[1:].isdigit():
                            pat = t_val
                        elif self._is_num(t_val):
                            nums.append(t_val)
                        i += 1

                    if node_type == 'J':
                        elev = nums[0] if len(nums) > 0 else "0"
                        dem = nums[1] if len(nums) > 1 else "0"
                        if dem != "0" and dem != "1":
                            junctions.append(f"{node_id}\t{elev}\t{dem}\t{pat}" if pat else f"{node_id}\t{elev}\t{dem}")
                        else:
                            junctions.append(f"{node_id}\t{elev}\t0")

                    elif node_type == 'S':
                        elev = nums[0] if len(nums) > 0 else "0"
                        reservoirs.append(f"{node_id}\t{elev}")

                    elif node_type == 'T':
                        elev = nums[0] if len(nums) > 0 else "0"
                        init = nums[1] if len(nums) > 1 else "0"
                        minl = nums[2] if len(nums) > 2 else "0"
                        maxl = nums[3] if len(nums) > 3 else "0"
                        diam = nums[4] if len(nums) > 4 else "0"
                        tanks.append(f"{node_id}\t{elev}\t{init}\t{minl}\t{maxl}\t{diam}")
                    continue
                i += 1
                continue

            if current_type == 'LINKS':
                if not (val.startswith('P') or val.startswith('N') or val.startswith('V')) or not val[1:].isdigit():
                    i += 1
                    continue

                link_id = val
                link_type = val[0]

                node1 = None
                node2 = None
                i += 1
                while i < n and (node1 is None or node2 is None):
                    if tokens[i]['type'] == 'STR':
                        if node1 is None:
                            node1 = tokens[i]['val']
                        else:
                            node2 = tokens[i]['val']
                    i += 1

                if not node1 or not node2:
                    continue

                if link_type == 'P':
                    length, diam, rough = "100", "50", "100"
                    stat = "Open"
                    nums = []
                    while i < n:
                        t_typ = tokens[i]['type']
                        t_val = tokens[i]['val']
                        if t_typ != 'STR':
                            i += 1
                            continue

                        if (t_val.startswith('P') or t_val.startswith('N') or t_val.startswith('V')) and t_val[1:].isdigit():
                            break
                        if t_val in ("Open", "Closed", "CV"):
                            stat = t_val
                            i += 1
                            break
                        if self._is_num(t_val):
                            nums.append(t_val)
                        i += 1

                    if len(nums) >= 1: length = nums[0]
                    if len(nums) >= 2: diam = nums[1]
                    if len(nums) >= 3: rough = nums[2]

                    pipes.append(f"{link_id}\t{node1}\t{node2}\t{length}\t{diam}\t{rough}")
                    if stat != "Open":
                        status.append(f"{link_id}\t{stat}")
                    continue

                elif link_type == 'N':
                    curve = ""
                    stat = "Open"
                    while i < n:
                        t_typ = tokens[i]['type']
                        t_val = tokens[i]['val']
                        if t_typ != 'STR':
                            i += 1
                            continue

                        if (t_val.startswith('P') or t_val.startswith('N') or t_val.startswith('V')) and t_val[1:].isdigit():
                            break
                        if t_val.startswith('K') and t_val[1:].isdigit():
                            curve = t_val
                        elif t_val in ("Open", "Closed"):
                            stat = t_val
                        i += 1

                    if curve:
                        pumps.append(f"{link_id}\t{node1}\t{node2}\tHEAD {curve}")
                    else:
                        pumps.append(f"{link_id}\t{node1}\t{node2}")

                    if stat != "Open":
                        status.append(f"{link_id}\t{stat}")
                    continue

                elif link_type == 'V':
                    diam, vtype, sett = "50", "PRV", "0"
                    stat = "None"
                    nums = []
                    while i < n:
                        t_typ = tokens[i]['type']
                        t_val = tokens[i]['val']
                        if t_typ != 'STR':
                            i += 1
                            continue

                        if (t_val.startswith('P') or t_val.startswith('N') or t_val.startswith('V')) and t_val[1:].isdigit():
                            break
                        if t_val in ("PRV", "PSV", "PBV", "FCV", "TCV", "GPV"):
                            vtype = t_val
                        elif t_val in ("Open", "Closed", "None"):
                            stat = t_val
                        elif self._is_num(t_val):
                            nums.append(t_val)
                        i += 1

                    if len(nums) >= 1: diam = nums[0]
                    if len(nums) >= 2: sett = nums[1]

                    valves.append(f"{link_id}\t{node1}\t{node2}\t{diam}\t{vtype}\t{sett}")
                    if stat not in ("None", "Open"):
                        status.append(f"{link_id}\t{stat}")
                    continue

        self._add_section("[OPTIONS]", options)
        self._add_section("[PATTERNS]", patterns)
        self._add_section("[CURVES]", curves)
        self._add_section("[JUNCTIONS]", junctions)
        self._add_section("[RESERVOIRS]", reservoirs)
        self._add_section("[TANKS]", tanks)
        self._add_section("[PIPES]", pipes)
        self._add_section("[PUMPS]", pumps)
        self._add_section("[VALVES]", valves)
        self._add_section("[STATUS]", status)
        self._add_section("[COORDINATES]", coordinates)
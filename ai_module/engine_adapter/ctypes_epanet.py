import ctypes
import os
import platform
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ai_module.config.settings import SRC_ENGINES_DIR

# EPANET 2.2 Enums (from SRC_engines/epanet2_enums.h)
EN_ELEVATION = 0
EN_BASEDEMAND = 1
EN_TANKLEVEL = 8
EN_DEMAND = 9
EN_HEAD = 10
EN_PRESSURE = 11
EN_QUALITY = 12
EN_TANKDIAM = 17
EN_MINLEVEL = 20
EN_MAXLEVEL = 21

EN_DIAMETER = 0
EN_LENGTH = 1
EN_ROUGHNESS = 2
EN_MINORLOSS = 3
EN_INITSTATUS = 4
EN_FLOW = 8
EN_VELOCITY = 9
EN_HEADLOSS = 10
EN_STATUS = 11
EN_SETTING = 12
EN_ENERGY = 13

EN_DURATION = 0
EN_HYDSTEP = 1
EN_REPORTSTEP = 5

EN_NODECOUNT = 0
EN_TANKCOUNT = 1
EN_LINKCOUNT = 2

EN_JUNCTION = 0
EN_RESERVOIR = 1
EN_TANK = 2

EN_CVPIPE = 0
EN_PIPE = 1
EN_PUMP = 2
EN_PRV = 3
EN_PSV = 4
EN_PBV = 5
EN_FCV = 6
EN_TCV = 7
EN_GPV = 8

FLOW_UNITS_MAP = {
    0: ("CFS", "US"),
    1: ("GPM", "US"),
    2: ("MGD", "US"),
    3: ("IMGD", "US"),
    4: ("AFD", "US"),
    5: ("LPS", "SI"),
    6: ("LPM", "SI"),
    7: ("MLD", "SI"),
    8: ("CMH", "SI"),
    9: ("CMD", "SI"),
}

NODE_TYPE_MAP = {
    EN_JUNCTION: "junction",
    EN_RESERVOIR: "reservoir",
    EN_TANK: "tank",
}

LINK_TYPE_MAP = {
    EN_CVPIPE: "pipe_cv",
    EN_PIPE: "pipe",
    EN_PUMP: "pump",
    EN_PRV: "valve_prv",
    EN_PSV: "valve_psv",
    EN_PBV: "valve_pbv",
    EN_FCV: "valve_fcv",
    EN_TCV: "valve_tcv",
    EN_GPV: "valve_gpv",
}


class EpanetEngineAdapter:
    """
    Direct ctypes wrapper over EPANET 2.2 C engine (SRC_engines).
    Automatically locates or compiles epanet2.dll (Windows) / libepanet2.so (Linux).
    Executes hydraulic and water quality simulations deterministically.
    """

    def __init__(self, lib_path: Optional[str] = None):
        self.lib_path = self._resolve_or_build_library(lib_path)
        self.lib = ctypes.CDLL(str(self.lib_path))
        self._setup_signatures()

    def _resolve_or_build_library(self, custom_path: Optional[str] = None) -> Path:
        if custom_path and Path(custom_path).exists():
            return Path(custom_path)

        adapter_dir = Path(__file__).resolve().parent
        is_windows = platform.system().lower().startswith("win")
        lib_name = "epanet2.dll" if is_windows else "libepanet2.so"
        candidate = adapter_dir / lib_name
        if candidate.exists():
            return candidate

        # Check /tmp fallback
        tmp_candidate = Path("/tmp") / lib_name
        if tmp_candidate.exists():
            return tmp_candidate

        # Compile from SRC_engines automatically if GCC/Clang is available
        c_files = [
            "epanet.c", "epanet2.c", "genmmd.c", "hash.c", "hydcoeffs.c",
            "hydraul.c", "hydsolver.c", "hydstatus.c", "inpfile.c",
            "input1.c", "input2.c", "input3.c", "mempool.c", "output.c",
            "project.c", "quality.c", "qualreact.c", "qualroute.c",
            "report.c", "rules.c", "smatrix.c",
        ]
        src_paths = [str(SRC_ENGINES_DIR / f) for f in c_files]
        cmd = ["gcc", "-O2", "-fPIC", "-shared"] + src_paths + ["-lm", "-o", str(candidate)]
        subprocess.run(cmd, check=True)
        return candidate

    def _setup_signatures(self) -> None:
        c_void_p = ctypes.c_void_p
        c_int = ctypes.c_int
        c_long = ctypes.c_long
        c_double = ctypes.c_double
        c_char_p = ctypes.c_char_p

        self.lib.EN_createproject.argtypes = [ctypes.POINTER(c_void_p)]
        self.lib.EN_createproject.restype = c_int

        self.lib.EN_deleteproject.argtypes = [c_void_p]
        self.lib.EN_deleteproject.restype = c_int

        self.lib.EN_open.argtypes = [c_void_p, c_char_p, c_char_p, c_char_p]
        self.lib.EN_open.restype = c_int

        self.lib.EN_close.argtypes = [c_void_p]
        self.lib.EN_close.restype = c_int

        self.lib.EN_getcount.argtypes = [c_void_p, c_int, ctypes.POINTER(c_int)]
        self.lib.EN_getcount.restype = c_int

        self.lib.EN_getflowunits.argtypes = [c_void_p, ctypes.POINTER(c_int)]
        self.lib.EN_getflowunits.restype = c_int

        self.lib.EN_gettimeparam.argtypes = [c_void_p, c_int, ctypes.POINTER(c_long)]
        self.lib.EN_gettimeparam.restype = c_int

        self.lib.EN_getnodeid.argtypes = [c_void_p, c_int, c_char_p]
        self.lib.EN_getnodeid.restype = c_int

        self.lib.EN_getnodetype.argtypes = [c_void_p, c_int, ctypes.POINTER(c_int)]
        self.lib.EN_getnodetype.restype = c_int

        self.lib.EN_getnodevalue.argtypes = [c_void_p, c_int, c_int, ctypes.POINTER(c_double)]
        self.lib.EN_getnodevalue.restype = c_int

        self.lib.EN_getcoord.argtypes = [c_void_p, c_int, ctypes.POINTER(c_double), ctypes.POINTER(c_double)]
        self.lib.EN_getcoord.restype = c_int

        self.lib.EN_getlinkid.argtypes = [c_void_p, c_int, c_char_p]
        self.lib.EN_getlinkid.restype = c_int

        self.lib.EN_getlinktype.argtypes = [c_void_p, c_int, ctypes.POINTER(c_int)]
        self.lib.EN_getlinktype.restype = c_int

        self.lib.EN_getlinknodes.argtypes = [c_void_p, c_int, ctypes.POINTER(c_int), ctypes.POINTER(c_int)]
        self.lib.EN_getlinknodes.restype = c_int

        self.lib.EN_getlinkvalue.argtypes = [c_void_p, c_int, c_int, ctypes.POINTER(c_double)]
        self.lib.EN_getlinkvalue.restype = c_int

        self.lib.EN_openH.argtypes = [c_void_p]
        self.lib.EN_openH.restype = c_int

        self.lib.EN_initH.argtypes = [c_void_p, c_int]
        self.lib.EN_initH.restype = c_int

        self.lib.EN_runH.argtypes = [c_void_p, ctypes.POINTER(c_long)]
        self.lib.EN_runH.restype = c_int

        self.lib.EN_nextH.argtypes = [c_void_p, ctypes.POINTER(c_long)]
        self.lib.EN_nextH.restype = c_int

        self.lib.EN_closeH.argtypes = [c_void_p]
        self.lib.EN_closeH.restype = c_int

        self.lib.EN_openQ.argtypes = [c_void_p]
        self.lib.EN_openQ.restype = c_int

        self.lib.EN_initQ.argtypes = [c_void_p, c_int]
        self.lib.EN_initQ.restype = c_int

        self.lib.EN_runQ.argtypes = [c_void_p, ctypes.POINTER(c_long)]
        self.lib.EN_runQ.restype = c_int

        self.lib.EN_nextQ.argtypes = [c_void_p, ctypes.POINTER(c_long)]
        self.lib.EN_nextQ.restype = c_int

        self.lib.EN_closeQ.argtypes = [c_void_p]
        self.lib.EN_closeQ.restype = c_int

    @staticmethod
    def _parse_inp_coordinates(inp_path: Path) -> Dict[str, Tuple[float, float]]:
        """Fallback parser for [COORDINATES] section in .INP file."""
        coords: Dict[str, Tuple[float, float]] = {}
        in_coords = False
        if not inp_path.exists():
            return coords
        for raw_line in inp_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(";"):
                continue
            if line.startswith("["):
                in_coords = line.upper().startswith("[COORD")
                continue
            if in_coords:
                parts = line.split()
                if len(parts) >= 3:
                    try:
                        coords[parts[0]] = (float(parts[1]), float(parts[2]))
                    except ValueError:
                        pass
        return coords

    def run_simulation(self, inp_file: str, target_period: int = 0) -> Dict[str, Any]:
        """
        Runs full hydraulic & water-quality simulation on `inp_file` using EPANET 2.2 C engine
        and returns structured project metadata, time steps, node states, and link states.
        All engineering metrics are also normalized to SI (m, L/s, m/s, mm) for consistent analytics.
        """
        inp_path = Path(inp_file).resolve()
        if not inp_path.exists():
            raise FileNotFoundError(f"INP file not found: {inp_path}")

        fallback_coords = self._parse_inp_coordinates(inp_path)

        ph = ctypes.c_void_p()
        self.lib.EN_createproject(ctypes.byref(ph))

        with tempfile.TemporaryDirectory() as tmpdir:
            rpt_path = os.path.join(tmpdir, "run.rpt")
            out_path = os.path.join(tmpdir, "run.out")

            err = self.lib.EN_open(
                ph,
                str(inp_path).encode("utf-8"),
                rpt_path.encode("utf-8"),
                out_path.encode("utf-8"),
            )
            if err != 0:
                self.lib.EN_deleteproject(ph)
                raise RuntimeError(f"EPANET EN_open failed with error code {err} on {inp_path.name}")

            try:
                # Get counts & units
                n_nodes = ctypes.c_int()
                n_tanks = ctypes.c_int()
                n_links = ctypes.c_int()
                flow_units_code = ctypes.c_int()
                duration_sec = ctypes.c_long()
                hyd_step_sec = ctypes.c_long()

                self.lib.EN_getcount(ph, EN_NODECOUNT, ctypes.byref(n_nodes))
                self.lib.EN_getcount(ph, EN_TANKCOUNT, ctypes.byref(n_tanks))
                self.lib.EN_getcount(ph, EN_LINKCOUNT, ctypes.byref(n_links))
                self.lib.EN_getflowunits(ph, ctypes.byref(flow_units_code))
                self.lib.EN_gettimeparam(ph, EN_DURATION, ctypes.byref(duration_sec))
                self.lib.EN_gettimeparam(ph, EN_HYDSTEP, ctypes.byref(hyd_step_sec))

                flow_units_str, unit_system = FLOW_UNITS_MAP.get(flow_units_code.value, ("LPS", "SI"))
                is_us = unit_system == "US"

                # Unit conversion factors to SI (meters, L/s, m/s, mm)
                len_to_m = 0.3048 if is_us else 1.0
                press_to_m = 0.70325 if is_us else 1.0  # 1 psi = 0.70325 m H2O
                diam_to_mm = 25.4 if is_us else 1.0
                vel_to_mps = 0.3048 if is_us else 1.0
                flow_to_lps_map = {
                    "CFS": 28.3168,
                    "GPM": 0.0630902,
                    "MGD": 43.8126,
                    "IMGD": 52.6168,
                    "AFD": 14.2764,
                    "LPS": 1.0,
                    "LPM": 1.0 / 60.0,
                    "MLD": 11.5741,
                    "CMH": 1.0 / 3.6,
                    "CMD": 1.0 / 86.4,
                }
                flow_to_lps = flow_to_lps_map.get(flow_units_str, 1.0)

                # Static node metadata
                nodes_meta: List[Dict[str, Any]] = []
                junctions_count = 0
                reservoirs_count = 0
                tanks_only_count = 0

                for idx in range(1, n_nodes.value + 1):
                    buf = ctypes.create_string_buffer(64)
                    ntype = ctypes.c_int()
                    elev = ctypes.c_double()
                    base_d = ctypes.c_double()
                    cx = ctypes.c_double()
                    cy = ctypes.c_double()

                    self.lib.EN_getnodeid(ph, idx, buf)
                    self.lib.EN_getnodetype(ph, idx, ctypes.byref(ntype))
                    self.lib.EN_getnodevalue(ph, idx, EN_ELEVATION, ctypes.byref(elev))
                    self.lib.EN_getnodevalue(ph, idx, EN_BASEDEMAND, ctypes.byref(base_d))
                    coord_err = self.lib.EN_getcoord(ph, idx, ctypes.byref(cx), ctypes.byref(cy))

                    node_id = buf.value.decode("utf-8", errors="ignore")
                    ntype_str = NODE_TYPE_MAP.get(ntype.value, "junction")
                    if ntype_str == "junction":
                        junctions_count += 1
                    elif ntype_str == "reservoir":
                        reservoirs_count += 1
                    elif ntype_str == "tank":
                        tanks_only_count += 1

                    x_val, y_val = cx.value, cy.value
                    if (coord_err != 0 or (x_val == 0.0 and y_val == 0.0)) and node_id in fallback_coords:
                        x_val, y_val = fallback_coords[node_id]

                    nodes_meta.append({
                        "index": idx,
                        "id": node_id,
                        "type": ntype_str,
                        "elevation_m": round(elev.value * len_to_m, 3),
                        "base_demand_lps": round(base_d.value * flow_to_lps, 3),
                        "x": x_val,
                        "y": y_val,
                    })

                # Auto-layout coordinates if the INP file had no [COORDINATES] section
                if all(n["x"] == 0.0 and n["y"] == 0.0 for n in nodes_meta):
                    import math
                    total_n = max(len(nodes_meta), 1)
                    cols = max(int(math.ceil(math.sqrt(total_n))), 2)
                    for idx_i, n in enumerate(nodes_meta):
                        r = idx_i // cols
                        c = idx_i % cols
                        n["x"] = float(100 + c * 220)
                        n["y"] = float(100 + r * 180)

                # Static link metadata
                links_meta: List[Dict[str, Any]] = []
                pipes_count = 0
                pumps_count = 0
                valves_count = 0

                for idx in range(1, n_links.value + 1):
                    buf = ctypes.create_string_buffer(64)
                    ltype = ctypes.c_int()
                    n1 = ctypes.c_int()
                    n2 = ctypes.c_int()
                    diam = ctypes.c_double()
                    length = ctypes.c_double()
                    rough = ctypes.c_double()

                    self.lib.EN_getlinkid(ph, idx, buf)
                    self.lib.EN_getlinktype(ph, idx, ctypes.byref(ltype))
                    self.lib.EN_getlinknodes(ph, idx, ctypes.byref(n1), ctypes.byref(n2))
                    self.lib.EN_getlinkvalue(ph, idx, EN_DIAMETER, ctypes.byref(diam))
                    self.lib.EN_getlinkvalue(ph, idx, EN_LENGTH, ctypes.byref(length))
                    self.lib.EN_getlinkvalue(ph, idx, EN_ROUGHNESS, ctypes.byref(rough))

                    link_id = buf.value.decode("utf-8", errors="ignore")
                    ltype_str = LINK_TYPE_MAP.get(ltype.value, "pipe")
                    if "pipe" in ltype_str:
                        pipes_count += 1
                    elif ltype_str == "pump":
                        pumps_count += 1
                    else:
                        valves_count += 1

                    links_meta.append({
                        "index": idx,
                        "id": link_id,
                        "type": ltype_str,
                        "from_node": nodes_meta[n1.value - 1]["id"],
                        "to_node": nodes_meta[n2.value - 1]["id"],
                        "diameter_mm": round(diam.value * diam_to_mm, 2),
                        "length_m": round(length.value * len_to_m, 2),
                        "roughness": round(rough.value, 3),
                    })

                # Run step-by-step Hydraulic & Quality simulation
                self.lib.EN_openH(ph)
                self.lib.EN_initH(ph, 0)

                snapshots: List[Dict[str, Any]] = []
                t = ctypes.c_long(0)
                tstep = ctypes.c_long(1)
                warnings_encountered = False

                while True:
                    run_code = self.lib.EN_runH(ph, ctypes.byref(t))
                    if run_code > 0:
                        warnings_encountered = True
                    if run_code > 100:
                        break

                    # Record snapshot at regular hydraulic steps or at t=0
                    if len(snapshots) == 0 or (hyd_step_sec.value > 0 and t.value % hyd_step_sec.value == 0):
                        node_states: Dict[str, Dict[str, float]] = {}
                        for nm in nodes_meta:
                            idx = nm["index"]
                            d_val = ctypes.c_double()
                            h_val = ctypes.c_double()
                            p_val = ctypes.c_double()
                            q_val = ctypes.c_double()
                            self.lib.EN_getnodevalue(ph, idx, EN_DEMAND, ctypes.byref(d_val))
                            self.lib.EN_getnodevalue(ph, idx, EN_HEAD, ctypes.byref(h_val))
                            self.lib.EN_getnodevalue(ph, idx, EN_PRESSURE, ctypes.byref(p_val))
                            self.lib.EN_getnodevalue(ph, idx, EN_QUALITY, ctypes.byref(q_val))

                            node_states[nm["id"]] = {
                                "demand_lps": round(d_val.value * flow_to_lps, 3),
                                "head_m": round(h_val.value * len_to_m, 3),
                                "pressure_m": round(p_val.value * press_to_m, 3),
                                "quality": round(q_val.value, 3),
                            }

                        link_states: Dict[str, Dict[str, Any]] = {}
                        for lm in links_meta:
                            idx = lm["index"]
                            fl_val = ctypes.c_double()
                            vl_val = ctypes.c_double()
                            hl_val = ctypes.c_double()
                            st_val = ctypes.c_double()
                            self.lib.EN_getlinkvalue(ph, idx, EN_FLOW, ctypes.byref(fl_val))
                            self.lib.EN_getlinkvalue(ph, idx, EN_VELOCITY, ctypes.byref(vl_val))
                            self.lib.EN_getlinkvalue(ph, idx, EN_HEADLOSS, ctypes.byref(hl_val))
                            self.lib.EN_getlinkvalue(ph, idx, EN_STATUS, ctypes.byref(st_val))

                            # In EPANET, EN_HEADLOSS for pipes is per 1000 ft (US) or per 1000 m (SI)
                            # which is numerically identical to m/km (dimensionless gradient * 1000)!
                            hl_val_num = hl_val.value
                            if lm["type"] == "pump":
                                hl_m_per_km = round(hl_val_num * len_to_m, 3)
                            else:
                                hl_m_per_km = round(abs(hl_val_num), 3)

                            link_states[lm["id"]] = {
                                "flow_lps": round(fl_val.value * flow_to_lps, 3),
                                "velocity_mps": round(vl_val.value * vel_to_mps, 3),
                                "headloss_m_per_km": hl_m_per_km,
                                "status": "OPEN" if st_val.value >= 1.0 else "CLOSED",
                            }

                        snapshots.append({
                            "period_index": len(snapshots),
                            "time_sec": int(t.value),
                            "time_h": round(t.value / 3600.0, 2),
                            "nodes": node_states,
                            "links": link_states,
                        })

                    self.lib.EN_nextH(ph, ctypes.byref(tstep))
                    if tstep.value <= 0:
                        break

                self.lib.EN_closeH(ph)

                if not snapshots:
                    raise RuntimeError("No hydraulic snapshots were generated.")

                chosen_idx = min(max(target_period, 0), len(snapshots) - 1)
                active_snapshot = snapshots[chosen_idx]

                return {
                    "project": {
                        "name": inp_path.stem,
                        "inp_file": str(inp_path),
                        "flow_units_native": flow_units_str,
                        "unit_system_native": unit_system,
                        "normalized_units": "SI (m, L/s, m/s, mm)",
                    },
                    "analysis": {
                        "type": "extended_period" if duration_sec.value > 0 else "steady_state",
                        "duration_h": round(duration_sec.value / 3600.0, 2),
                        "step_h": round(hyd_step_sec.value / 3600.0, 2) if hyd_step_sec.value > 0 else 1.0,
                        "total_periods": len(snapshots),
                        "active_period": chosen_idx,
                        "active_time_h": active_snapshot["time_h"],
                        "status": "converged_with_warnings" if warnings_encountered else "converged",
                    },
                    "network_summary": {
                        "junctions": junctions_count,
                        "reservoirs": reservoirs_count,
                        "tanks": tanks_only_count,
                        "pipes": pipes_count,
                        "pumps": pumps_count,
                        "valves": valves_count,
                        "total_nodes": n_nodes.value,
                        "total_links": n_links.value,
                    },
                    "topology": {
                        "nodes": nodes_meta,
                        "links": links_meta,
                    },
                    "active_snapshot": active_snapshot,
                    "all_snapshots": snapshots,
                }
            finally:
                self.lib.EN_close(ph)
                self.lib.EN_deleteproject(ph)

# Data structures related to simulation output files

import re
import pathlib
import warnings
import numpy as np
import pandas as pd
import astropy.stats as aps
import scipy.signal as scs
import scipy.constants as scc
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import matplotlib.cm as cm
from . import statutil
from . import ioutil
from . import ovftools
import tqdm


class DomainWall:

    def __init__(self, root, name='domainwall'):
        self.config = []
        self.time = []
        self.root = root
        self.window_pos = []

        files = []
        for item in self.root.iterdir():
            if re.search(f'{name}'+r'\d{6}.csv', item.name) is not None:
                files.append(self.root / item.name)

        if len(files) == 0:
            raise ValueError('No domain wall files found.')

        files = sorted(files)
        for item in tqdm.tqdm(files, desc='Reading domain wall configs'):
            self.append(item)

        return

    def append(self, fname):
        with open(fname, 'r') as f:
            self.time.append(float(f.readline().split('#time = ')[1]))
            line = f.readline()
            if '#window_position' in line:
                try:
                    self.window_pos.append(float(line.split('#window_position = ')[1]))
                except:
                    self.window_pos.append(0)

            else:
                self.window_pos.append(0)

        df = pd.read_csv(fname, sep=',', comment='#')
        self.config.append(df)
        return

    def __len__(self):
        return len(self.time)

    def get_window_pos(self):
        if np.any(np.isnan(self.window_pos)):
            warnings.warn('No window position header found.')
            return 0
        else:
            return self.window_pos

    def __getitem__(self, i):
        return self.config[i]


class SimData:
    """This class holds output data from a single simulation.

    """

    VALID_TIMESERIES = ['t', 'vdw', 'Axy', 'Az']

    def __init__(self, data_dir, script='', threshold=0.1, drop_duplicates=False):

        self.data_dir = ioutil.pathize(data_dir)
        self.script = script or self.find_script()
        self.table = pd.read_csv((self.data_dir / 'table.txt').as_posix(), sep='\t')

        if drop_duplicates:
            self.table = self.table.drop_duplicates('# t (s)')

        self.threshold = threshold
        self.seismograph = {}
        self.wall = None

        return

    def find_script(self):
        for item in self.data_dir.iterdir():
            if item.suffix == '.mx3':
                return self.data_dir / item
        return ''

    def get_simulation_time(self):

        with (self.data_dir / 'log.txt').open(mode='r') as f:
            lines = f.readlines()

        for line in lines:
            if '//Total simulation time:' in line:
                return float(line.split('//Total simulation time:  ')[-1])

        raise ValueError('No time found.')

    def Axy(self):
        return self.table['ext_axy (rad/s)'].values

    def Az(self):
        return self.table['ext_az (rad/s)'].values

    def vdw(self, vdwcol=None):
        if vdwcol is None:
            for vdwcol in ['ext_exactdwvelavg (m/s)', 'ext_dwfinespeed (m/s)', 'ext_exactdwvelzc (m/s)']:
                if vdwcol in self.table:
                    return self.table[vdwcol].values
            raise ValueError('No vdw column in data.')
        else:
            return self.table[vdwcol].values

    def dww(self):

        dwwcol = 'ext_dwwidth (m)'
        if dwwcol in self.table:
            return self.table[dwwcol].values
        else:
            raise ValueError('No dww column in data.')

    def dwpos(self):
        return self.table['ext_exactdwposavg (m)'].values

    def shift(self):
        return self.table['ext_dwpos (m)'].values

    def t(self):
        return self.table['# t (s)'].values

    def get_seismograph(self, key='vdw'):
        if key in self.VALID_TIMESERIES:
            if key not in self.seismograph:
                self.seismograph[key] = statutil.Seismograph(t=self.t(), v=self.vdw(), vt=self.threshold, s=getattr(self, key)())
            return self.seismograph[key]
        else:
            raise ValueError(f'Seismograph requested ({key}) is not a valid timeseries: {self.VALID_TIMESERIES}')

    def get_avalanche_sizes(self, key='vdw'):
        s = self.get_seismograph(key)
        return s.sizes

    def get_avalanche_durations(self):
        s = self.get_seismograph()
        return s.durations

    def get_wall(self, name='domainwall'):
        if self.wall is None:
            self.wall = DomainWall(self.data_dir, name=name)
        return self.wall

    def avg_vdw(self, t_cutoff):
        return np.mean(self.vdw()[self.t() > t_cutoff])

    def avg_dww(self, t_cutoff):
        return np.mean(self.dww()[self.t() > t_cutoff])

    def std_vdw(self, t_cutoff):
        return np.std(self.vdw()[self.t() > t_cutoff])

    def std_dww(self, t_cutoff):
        return np.std(self.dww()[self.t() > t_cutoff])

    def avg_dt(self):
        return np.mean(self.dt())

    def dt(self):
        return np.diff(self.t())

    def precession_freq(self):
        tf, vf = aps.LombScargle(self.t(), self.vdw()).autopower()
        peaks, _ = scs.find_peaks(vf, height=np.max(vf)*0.9)
        if len(peaks) > 0:
            return tf[peaks[0]]
        else:
            return np.nan

    def Bw_lower_bound(self, B, alpha):
        """If below the walker field Bw, we can estimate the lower bound of the walker field based on the integration
        time and the applied field.

        Parameters
        ----------
        B : float
            Applied field [T]
        alpha : float
            Gilbert damping parameter

        Returns
        -------
        float
            Lower bound for the walker field
        """

        return Bw(B, self.t()[-1], alpha)

    def events_by_duration(self, duration, tol):
        """Get V(t) of all events with durations falling in the interval [duration-tol, duration+tol]"""

        event_lengths = self.get_seismograph().durations
        i_start = self.get_seismograph().istart
        i_stop = self.get_seismograph().istop

        signals = []
        times = []

        for e_length, start, stop in zip(event_lengths, i_start, i_stop):
            if duration-tol < e_length < duration+tol:
                signals.append(self.vdw()[start:stop])
                times.append(self.t()[start:stop])

        return times, signals


class SimRun:
    """Simulations are run in batches. This class holds a set of simulation outputs as SimData objects.

    """

    def __init__(self, root=None, drop_duplicates=False, simulations=None, metadata=None):

        if root is not None:
            self.root = pathlib.Path(root)

            if (self.root / 'slurm_map.csv').is_file():

                # Get the metadata from the slurm map
                _metadata = pd.read_csv((self.root / 'slurm_map.csv').as_posix(), sep=',')
                scripts = [(self.root / script).as_posix() for script in _metadata['script'].values]
                _metadata['script'] = scripts

                # Ignore any entries which either are missing the input script or the output directory
                _valid_indices = []
                for i in tqdm.trange(len(_metadata), desc='Reading simulation data'):
                    _script = pathlib.Path(_metadata.iloc[i]['script'])
                    if _script.exists() and (self.root / f'{_script.stem}.out').exists():
                        _valid_indices.append(i)

                self.metadata = _metadata.iloc[_valid_indices]

            else:
                self.metadata = get_metadata(self.root)
            self.simulations = self._get_simulations(drop_duplicates)

        elif simulations is not None:
            if metadata is not None:
                self.metadata = metadata
            self.simulations = simulations

        else:
            raise NotImplementedError

        return

    def _get_simulations(self, drop_duplicates=False):

        _s = []
        for _, row in self.metadata.iterrows():
            script = self.root / row['script']
            _s.append(SimData(script=script,
                              data_dir=self.root / f'{script.stem}.out',
                              drop_duplicates=drop_duplicates))

        return _s

    def get_simulation_times(self):
        return [sim.get_simulation_time() for sim in self.simulations]

    def __getitem__(self, i):

        if isinstance(i, slice):
            return SimRun(simulations=self.simulations[i], metadata=self.metadata.iloc[i])

        elif isinstance(i, int):
            return self.simulations[i]

        else:
            raise NotImplementedError

    def __setitem__(self, i, val):
        self.simulations[i] = val
        return

    def get_avalanche_durations(self):
        return np.hstack([sim.get_avalanche_durations() for sim in self.simulations])

    def get_avalanche_sizes(self, key='vdw'):
        return np.hstack([sim.get_avalanche_sizes(key=key) for sim in self.simulations])

    def __repr__(self):
        return self.metadata.to_html()

    def append_metadata(self, name, search_value):
        """Search through the input scripts for search_value, which is assumed to be a float. Store the found value
        for each script in self.metadata[name].
        """

        values = []
        for _, row in self.metadata.iterrows():
            values.append(find_in_script(row['script'], search_value))

        self.metadata[name] = values
        return

    def avg_vdws(self, t_cutoff=0):
        return [sim.avg_vdw(t_cutoff=t_cutoff) for sim in self.simulations]

    def avg_dwws(self, t_cutoff=0):
        return [sim.avg_dww(t_cutoff=t_cutoff) for sim in self.simulations]

    def std_vdws(self, t_cutoff=0):
        return [sim.std_vdw(t_cutoff=t_cutoff) for sim in self.simulations]

    def std_dwws(self, t_cutoff=0):
        return [sim.std_dww(t_cutoff=t_cutoff) for sim in self.simulations]

    def avg_dt(self):
        return np.mean([sim.avg_dt() for sim in self.simulations])

    def dt(self):
        return [sim.dt() for sim in self.simulations]

    def __len__(self):
        return len(self.simulations)

    def events_by_duration(self, duration, tol):
        times = []
        signals = []

        for sim in self.simulations:
            _t, _s = sim.events_by_duration(duration, tol)
            times += _t
            signals += _s

        return times, signals


def get_metadata(root):

    root = ioutil.pathize(root)

    data = {}
    for item in sorted(root.iterdir()):
        script = root / (item.stem + '.mx3')
        if item.is_dir() and script.exists():
            check_dict_add_val(data, 'script', script.as_posix())

    return pd.DataFrame(data)


def check_dict_add_val(data, key, value):
    if key in data:
        data[key].append(value)
    else:
        data[key] = [value]
    return


def find_in_script(script, key):

    script = ioutil.pathize(script)

    with script.open('r') as f:
        lines = f.readlines()

    for line in lines:
        if key in line:
            return float(line.split(sep=key)[-1].split()[0])

    raise ValueError(f'Key {key} not found in script {script}')


def Bw(B, T, alpha):
    """When below the walker field, the magnetization will precess. Estimate the walker field given some integration
    time and applied field, assuming the period of precession is exactly the length of time you spent integrating.
    This gives a lower bound on the walker field.

    Parameters
    ----------
    B : float
        Applied fiel
    T : float
        Integration time (precession frequency)
    alpha : float
        Gilbert damping parameter

    Returns
    -------
    float
        [description]
    """

    return np.sqrt(B**2 - ((2*scc.pi*(1+alpha**2))/(scc.physical_constants['electron gyromag. ratio'][0]*T))**2)


class OommfSim:

    def __init__(self, outdir):
        # Need to write a parser to get column names...for now, take the easy (fast) way out
        self.names = ['Oxs_CGEvolve::Max mxHxm',
                      'Oxs_CGEvolve::Total energy',
                      'Oxs_CGEvolve::Delta E',
                      'Oxs_CGEvolve::Bracket count',
                      'Oxs_CGEvolve::Line min count',
                      'Oxs_CGEvolve::Conjugate cycle count',
                      'Oxs_CGEvolve::Cycle count',
                      'Oxs_CGEvolve::Cycle sub count',
                      'Oxs_CGEvolve::Energy calc count',
                      'Oxs_UniformExchange::Energy',
                      'Oxs_UniformExchange::Max Spin Ang',
                      'Oxs_UniformExchange::Stage Max Spin Ang',
                      'Oxs_UniformExchange::Run Max Spin Ang',
                      'Oxs_Demag::Energy',
                      'Oxs_UZeeman::Energy',
                      'Oxs_UZeeman::B',
                      'Oxs_UZeeman::Bx',
                      'Oxs_UZeeman::By',
                      'Oxs_UZeeman::Bz',
                      'Oxs_UniaxialAnisotropy::Energy',
                      'Oxs_MinDriver::Iteration',
                      'Oxs_MinDriver::Stage iteration',
                      'Oxs_MinDriver::Stage',
                      'Oxs_MinDriver::mx',
                      'Oxs_MinDriver::my',
                      'Oxs_MinDriver::mz']

        self.outdir = pathlib.Path(outdir)
        self.mif = outdir / (outdir.stem + '.mif')
        self.spin = ovftools.group_unpack(outdir, pattern=outdir.stem)
        self.table = self.extract_odt(outdir)
        self.header = self.extract_header(outdir)

        return

    def extract_header(self, outdir):
        for item in sorted(pathlib.Path(self.outdir).iterdir()):
            if item.suffix == '.omf':
                return ovftools.read_header(item.as_posix())
        raise ValueError(f'No omf found in {self.outdir}')

    def extract_odt(self, outdir):
        for item in sorted(pathlib.Path(outdir).iterdir()):
            if item.suffix == '.odt':
                return pd.read_csv(item.as_posix(), sep=r'\s+', header=None, names=self.names, comment='#')
        raise ValueError(f'No odt found in {outdir}')

    def dwpos(self, dx=1e-9):
        pos = []
        for i in range(self.spin.shape[0]):
            pos.append(self._dwpos(self.spin[i, 0, :, :, 2], dx))

        return np.array(pos)

    def _dwpos(self, mz, dx):
        pct = 1-(1-np.mean(mz))/2

        return pct*self.nxyz()[0]*self.dxyz()[0]

    def e_demag(self):
        return self.table['Oxs_Demag::Energy']

    def b_z(self):
        return self.table['Oxs_UZeeman::Bz']

    def nxyz(self):
        return self.header['xnodes'], self.header['ynodes'], self.header['znodes']

    def dxyz(self):
        return self.header['xstepsize'], self.header['ystepsize'], self.header['zstepsize']

    def __len__(self):
        return self.spin.shape[0]

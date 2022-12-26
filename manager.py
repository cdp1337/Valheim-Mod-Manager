import os
import logging
import shutil
import requests
import time
import json
import datetime
import dateutil.parser
import re
import yaml
import zipfile
from pprint import pprint
from packaging import version


class PackageVersion:
    '''
    Individual version for a given package, each package may have multiple versions,
    any one of which may be installed (at a time)

    Attributes
    ----------
    created : datetime
        The datetime this version was published
    dependencies : list[str]
        List of dependencies
    description : str
        Description of this version
    url : str
        Download URL for this version
    downloads : int
        Number of downloads for this version
    size : int
        Filesize of this version (in bytes)
    version : str
        Version string of this version
    uuid : str
        Unique ID for this version
    '''

    def __init__(self, data: dict) -> None:
        self.created: datetime = dateutil.parser.isoparse(data['date_created'])
        self.dependencies: list = data['dependencies']
        self.description: str = data['description']
        self.url: str = data['download_url']
        self.downloads: int = data['downloads']
        self.size: int = data['file_size']
        self.version: str = data['version_number']
        self.uuid: str = data['uuid4']


class Package:
    '''
    A mod package from thunderstore.io, contains the bulk of the logic for working with mods.

    Attributes
    ----------
    categories : list[str]
        List of author-defined category tags
    created : datetime
        Date this mod was originally created
    update : datetime
        Date this mod was last updated
    name : str
        Name of this mod, also used to create the directory structure
    deprecated : bool
        If it's flagged as deprecated?  dunno
    owner : str
        Name of the author
    url : str
        URL on thunderstore.io to view this mod
    uuid : str
        Unique ID for this mod, useful because name is NOT unique!
    rating : int
        Rating score?  no idea what this is, but thunderstore.io provides it.
    versions : list[PackageVersion]
        List of all versions available for this mod
    selected_version : str|None
        Used when installing a specific version, set to the version string
    installed_version : str|None
        Set as the currently installed version string
    '''

    overrides = {
        'BepInExPack_Valheim': {
            'source': 'BepInExPack_Valheim/',
            'dest': ''
        }
    }

    def __init__(self, data: dict) -> None:
        self.categories: list = data['categories']
        self.created: datetime = dateutil.parser.isoparse(data['date_created'])
        self.update: datetime = dateutil.parser.isoparse(data['date_updated'])
        self.name: str = data['name']
        self.deprecated: bool = data['is_deprecated']
        self.owner: str = data['owner']
        self.url: str = data['package_url']
        self.uuid: str = data['uuid4']
        self.rating: int = data['rating_score']
        self.versions: list[PackageVersion] = []
        self.selected_version = None
        self.installed_version = None

        for i in data['versions']:
            self.versions.append(PackageVersion(i))
    
    def get_highest_version(self) -> PackageVersion:
        '''
        Get the latest version for this mod

        Returns
        -------
        PackageVersion
            The version object representing this request
        '''

        highest_num = None
        highest_pkg = None

        for v in self.versions:
            if highest_num is None:
                highest_num = v.version
                highest_pkg = v
            elif version.parse(v.version) > version.parse(highest_num):
                highest_num = v.version
                highest_pkg = v
        
        return highest_pkg
    
    def get_installed_version(self) -> PackageVersion:
        '''
        Get the currently installed version for this mod

        Returns
        -------
        PackageVersion
            The version object representing this request
        '''

        for v in self.versions:
            if self.installed_version == v.version:
                return v
    
    def get_version(self, vers: str) -> PackageVersion:
        '''
        Get a specific version for this mod based on its version string

        Parameters
        ----------
        vers : str
            Version string to retrieve

        Returns
        -------
        PackageVersion
            The version object representing this request
        '''
        for v in self.versions:
            if v.version == vers:
                return v
    
    def check_update_available(self) -> bool:
        '''
        Check if there is an update available for this mod

        Returns
        -------
        bool
            True/False if there's a newer version available in thunderstore.io
        '''
        installed = self.get_installed_version()
        latest = self.get_highest_version()

        if installed is None:
            # Not installed, no updates necessary
            return False
        
        return installed.version != latest.version

    def install(self):
        '''
        Install the `selected_version` of this mod into the local cache
        '''
        if self.selected_version is not None:
            v = self.get_version(self.selected_version)
        else:
            v = self.get_highest_version()
        
        logging.debug('Installing ' + self.name + ' ' + v.version)
        
        # Check any dependencies and install them first
        for d in v.dependencies:
            for p in ModPackages.search(d):
                if p.installed_version is None:
                    logging.debug('New dependency found, processing')
                    p.install()
                elif version.parse(p.installed_version) < version.parse(p.selected_version):
                    # Check if the installed is higher or it needs to be updated
                    logging.debug('Updated dependency found, processing')
                    p.install()
        
        target = self.name + '-' + v.version + '.zip'

        # Download the archive from the server (if it doesn't already exist)
        if not os.path.exists('.cache/packages/' + target):
            logging.debug('Downloading ' + v.url + ' to .cache/packages/' + target)
            webreq = requests.get(v.url)
            open('.cache/packages/' + target, 'wb').write(webreq.content)
        else:
            logging.debug('.cache/packages/' + target + ' already in cache, skipping download')
        
        # Extract the package (and optionally to server if set)
        self._extract_zip(target, 'client')
        if 'Server-side' in self.categories:
            self._extract_zip(target, 'server')
        
        # Update the install cache
        ModPackages.update_installed_cache(self, v.version)
        # Update installed version, (must be done AFTER update_installed_cache)
        self.installed_version = v.version

    def upgrade(self):
        '''
        Convenience method to select the latest version and install that
        '''
        self.selected_version = self.get_highest_version().version
        self.install()
    
    def remove(self):
        '''
        Remove this mod from the local cache
        '''
        c = os.path.join('.cache/client/BepInEx/plugins/', self.name)
        s = os.path.join('.cache/server/BepInEx/plugins/', self.name)

        if os.path.exists(c):
            logging.debug('Removing directory ' + c)
            shutil.rmtree(c)

        if os.path.exists(s):
            logging.debug('Removing directory ' + s)
            shutil.rmtree(s)
        
        ModPackages.update_installed_cache(self, None)
        self.installed_version = None
    
    def rollback(self):
        '''
        Rollback any modifications performed since the last deployment
        '''
        try:
            changes = ModPackages.changed[self.uuid]
        except KeyError:
            # No changes recorded, nothing to perform
            return
        
        if changes['old'] == changes['new']:
            # Changes recorded, but must have already been rolled back
            return
        
        if changes['old'] is None:
            self.remove()
        else:
            self.selected_version = changes['old']
            self.install()
    
    def _extract_zip(self, package: str, type: str):
        '''
        Internal method to extract a zip package into a given destination

        Parameters
        ----------
        package : str
            Local ZIP filename to extract, just the basename
        type : str
            Usually 'client' or 'server', allows the extract to target a specific destination type
        '''
        # Pull package overrides (if set)
        try:
            source = Package.overrides[self.name]['source']
        except:
            source = None
        
        try:
            dest = Package.overrides[self.name]['dest']
        except:
            dest = 'BepInEx/plugins/' + self.name
        
        with zipfile.ZipFile('.cache/packages/' + package) as zip:
            logging.debug('Extracting ' + package + ' to ' + type + '/' + dest)
            
            # Specifying a source needs to iterate over every file contained
            # because extractall will simply extract an empty directory.
            for f in zip.namelist():

                if source is not None:
                    # Only process files within the source directory (when specified)
                    if f.startswith(source):
                        filename = f[len(source):]
                    else:
                        filename = None
                else:
                    # Without source set filename is just the zipped file (further processing allowed)
                    filename = f
                
                if filename is not None:
                    # Valid file, continue for processing.

                    # Valweed uses '\' in its filenames for some reason, replace these with standard separators
                    filename = filename.replace('\\', '/')

                    # Valweed has its assets nested in a silly manner, fix that
                    check = 'plugins/' + self.name + '/'
                    if filename.startswith(check):
                        filename = filename[len(check):]
                    
                    # BetterArchery also does the "atm machine" trick, plugins/BetterArchery/BetterArchery/...
                    check = self.name + '/'
                    if filename.startswith(check):
                        filename = filename[len(check):]
                
                
                if not (filename is None or filename == '' or filename.endswith('/')):
                    filename = os.path.join('.cache/' + type + '/', dest, filename)
                    if not os.path.exists(os.path.dirname(filename)):
                        os.makedirs(os.path.dirname(filename))

                    sfile = zip.open(f)
                    dfile = open(filename, 'wb')
                    with sfile, dfile:
                        shutil.copyfileobj(sfile, dfile)


class ModPackages(object):
    '''
    Primary interface for working with mods

    Attributes
    ----------
    packages : list[Package]
        List of all packages found from thunderstore.io
    installed : dict
        Dictionary of curently installed mods, keyed with the mod name.
        Contains `uuid` (str), `version` (str), and `updated` (float)
    removed : list[str]
        Flat list of mod names removed since the last deployment, useful for keeping local game in sync with uninstalls
    config : dict
        Any configurable parameter within `config.yml`
    changed : dict
        Dictionary of changes pending for deployment, keyed with the mod UUID.
        contains `old` and `new` with either the version string or None for new installs / removals.
    '''

    _initialized = False
    packages: list[Package] = []
    installed = None
    removed = None
    config = None
    changed = None

    @classmethod
    def init(cls) -> None:
        '''
        Initialize the mod system.

        Will ensure the expected directory structure and load all necessary configuration parameters.
        '''
        if cls._initialized:
            # init only needs ran once
            return
        cls._initialized = True

        try:
            with open('config.yml', 'r') as file:
                cls.config = yaml.safe_load(file)
        except FileNotFoundError:
            logging.warn('Application configuration not set, please copy config.yml.DEFAULT to config.yml and configure as necessary')
            exit()
        
        # Set requested logging level (values are human friendly)
        if cls.config['debug']:
            logging.basicConfig(level=logging.DEBUG)
        
        # Ensure the meta directory exists
        if not os.path.exists('.cache'):
            logging.debug('Cache directory does not exist yet, creating')
            os.mkdir('.cache')
        
        if not os.path.exists('.cache/packages'):
            os.mkdir('.cache/packages')
        
        if not os.path.exists('.cache/client'):
            os.mkdir('.cache/client')

        if not os.path.exists('.cache/server'):
            os.mkdir('.cache/server')

        if not os.path.exists(cls.config['exportdir']):
            os.makedirs(cls.config['exportdir'])
        
        # Read the install data
        try:
            with open('.cache/installed.json', 'r') as fp:
                cls.installed = json.load(fp)
        except:
            cls.installed = {}
        
        # Read the removed data
        try:
            with open('.cache/removed.json', 'r') as fp:
                cls.removed = json.load(fp)
        except:
            cls.removed = []
        
        # Read the change data
        try:
            with open('.cache/changed.json', 'r') as fp:
                cls.changed = json.load(fp)
        except:
            cls.changed = {}

        # Ensure the packages.json file exists and is up to date
        if not os.path.exists('.cache/packages.json'):
            logging.debug('Packages data does not exist yet')
            cls.download_packages()
        else:
            timecheck = time.time() - 86400
            if os.path.getmtime('.cache/packages.json') < timecheck:
                logging.debug('Packages data out of date')
                cls.download_packages()
        
        # Load all packages data
        with open('.cache/packages.json', 'r') as fp:
            data = json.load(fp)
            for p in data:
                pkg = Package(p)
                try:
                    pkg.installed_version = cls.installed[pkg.name]['version']
                except KeyError:
                    pass
                cls.packages.append(pkg)
    
    @classmethod
    def download_packages(cls):
        '''
        Download the full list of all packages and store locally
        '''
        url = 'https://valheim.thunderstore.io/api/v1/package/'
        logging.debug('Downloading ' + url + ' to .cache/packages.json')
        webreq = requests.get(url)
        open('.cache/packages.json', 'wb').write(webreq.content)
    
    @classmethod
    def search(cls, query: str) -> list[Package]:
        '''
        Search for packages by name, URL, or author-name-version

        Parameters
        ----------
        query : str
            Query to search against, can be:
            "package name" for a simple search (usually from user input),
            "package URL" useful for installing a specific mod after browsing the site, or
            "author-name-version" dependency string
        
        Returns
        -------
        list[Package]
            Any/all packages located from the search.  Try searching for "chicken", you'll get several.
        '''
        owner = None
        name = None
        url = None

        if re.match('([^-]*)-([^-]*)-([^-]*)', query) is not None:
            # Matches owner-name-version, used in dependency checks
            # example, "MaGic-Quick_Deposit-1.0.1"
            groups = re.match('([^-]*)-([^-]*)-([^-]*)', query)
            owner = groups.group(1)
            name = groups.group(2)
            vers = groups.group(3)
            
        elif 'https://valheim.thunderstore.io/package/' in query:
            # https://valheim.thunderstore.io/package/CookieMilk/MajesticChickens/
            url = query
        else:
            # Allow the user to enter potentially loose information
            query = query.lower().replace(' ', '_')
        
        results = []

        for p in cls.packages:
            if name is not None:
                if p.owner == owner and p.name == name:
                    p.selected_version = vers
                    results.append(p)
            elif url is not None:
                if p.url == url:
                    results.append(p)
            else:
                if p.name.lower().find(query) != -1:
                    results.append(p)
        
        return results
    
    @classmethod
    def get_installed_packages(cls) -> list[Package]:
        '''
        Get all installed mods

        Returns
        -------
        list[Package]
            List of all mod packages currently installed
        '''
        uuids = []
        for k in cls.installed:
            uuids.append(cls.installed[k]['uuid'])
        
        return cls.get_by_uuids(uuids)
    
    @classmethod
    def get_by_uuid(cls, uuid: str) -> Package:
        '''
        Get a specific mod package from its UUID

        Returns
        -------
        Package
            The mod package
        '''
        for p in cls.packages:
            if p.uuid == uuid:
                return p
    
    @classmethod
    def get_by_uuids(cls, uuids: list[str]) -> list[Package]:
        '''
        Get multiple mods by their UUIDs (useful for not iterating through the full packages unnecessarily)

        Parameters
        ----------
        uuids : list[str]
            List of UUID strings to retrieve
        
        Returns
        -------
        list[Package]
            All packages with matching UUID string
        '''
        packages = []
        for p in cls.packages:
            if p.uuid in uuids:
                packages.append(p)
        
        # Sort them by name for convenience
        packages.sort(key=lambda pkg: pkg.name)
        return packages
    
    @classmethod
    def update_installed_cache(cls, pkg: Package, ver):
        '''
        Update the cache of packages installed

        Parameters
        ----------
        pkg : Package
            The package to flag as updated
        ver : str|None
            The version string (or None for removals) for the new version
        '''

        # Update changed for use in changelog and rolling back updates
        try:
            # Existing keys just update the new (in case a version is updated multiple times before deployment)
            cls.changed[pkg.uuid]['new'] = ver
        except KeyError:
            # New keys set both old and new
            cls.changed[pkg.uuid] = {
                'old': pkg.installed_version,
                'new': ver
            }

        if ver is None:
            # Package was removed
            try:
                del(cls.installed[pkg.name])
            except KeyError:
                pass
            
            if not pkg.name in cls.removed:
                cls.removed.append(pkg.name)
        else:
            # Package was updated / installed
            if pkg.name in cls.removed:
                del(cls.removed[cls.index(pkg.name)])

            cls.installed[pkg.name] = {
                'version': ver,
                'uuid': pkg.uuid,
                'updated': datetime.datetime.now().timestamp()
            }
        
        cls.installed = dict(sorted(cls.installed.items()))

        with open('.cache/installed.json', 'w') as fp:
            json.dump(cls.installed, fp, indent=4)
        
        with open('.cache/removed.json', 'w') as fp:
            json.dump(cls.removed, fp, indent=4)
        
        with open('.cache/changed.json', 'w') as fp:
            json.dump(cls.changed, fp, indent=4)
    
    @classmethod
    def sync_game(cls):
        '''
        Sync installed mods to the local game client (useful for testing)
        '''

        # Install mods from the local cache
        srcdir = '.cache/client/'
        for root, dirs, files in os.walk(srcdir):
            for f in files:
                s = os.path.join(root, f)
                d = os.path.join(cls.config['gamedir'], s[len(srcdir):])
                p = os.path.dirname(d)
                logging.debug('Copying file to ' + d)

                if not os.path.exists(p):
                    os.makedirs(p)
                
                shutil.copyfile(s, d)
        
        # Remove any 'removed' mod, this is important here because testing mods often involves removing ones which don't work
        for r in cls.removed:
            d = os.path.join(cls.config['gamedir'], 'BepInEx', 'plugins', r)
            if os.path.exists(d):
                logging.debug('Removing game mod ' + d)
                shutil.rmtree(d)
    
    @classmethod
    def get_synced_packages(cls) -> list[Package]:
        '''
        Get all packages which are installed in the local game client

        Returns
        -------
        list[Package]
            All mods currently installed in the local game directory
        '''
        packages = []
        d = os.path.join(cls.config['gamedir'], 'BepInEx', 'plugins')
        for root, dirs, files in os.walk(d):
            for f in files:
                if f == 'manifest.json':
                    manifest = os.path.join(root, f)
                    logging.debug('Found ' + manifest)
                    with open(manifest, 'r') as fp:
                        # Do this the hard way because manifests often contain UTF-8 characters
                        data = json.loads(fp.read().encode().decode('utf-8-sig'))
                        pkgs = cls.search(data['name'])
                        
                        if len(pkgs) == 0:
                            logging.warn('Unable to locate package for ' + manifest)
                        else:
                            # Search is a very open query, we want to be more exact.
                            for p in pkgs:
                                if p.name == data['name']:
                                    
                                    if p.name in cls.installed:
                                        # If it's already installed, we can narrow down to that specific UUID
                                        if p.uuid == cls.installed[p.name]['uuid']:
                                            p.selected_version = data['version_number']
                                            packages.append(p)
                                    else:
                                        # Not installed, try to narrow down which package based on versions available
                                        versions = []
                                        for v in p.versions:
                                            versions.append(v.version)
                                        
                                        if data['version_number'] in versions:
                                            p.selected_version = data['version_number']
                                            packages.append(p)
        
        return packages

    
    @classmethod
    def export_full(cls) -> str:
        '''
        Export all installed mods into a single ZIP archive for players

        Returns
        -------
        str
            Will return the filename generated
        '''

        srcdir = '.cache/client/'
        destzip = cls.config['exportprefix'] + '-' + datetime.datetime.now().strftime('%Y%m%d') + '.zip'
        ziptarget = os.path.join(cls.config['exportdir'], destzip)
        with zipfile.ZipFile(ziptarget, 'w') as zip:
            for root, dirs, files in os.walk(srcdir):
                for f in files:
                    p = os.path.join(root, f)
                    zip.write(p, arcname=p[len(srcdir):])
        
        return ziptarget
    
    @classmethod
    def export_updates(cls) -> str:
        '''
        Export updated mods into a single ZIP archive for players

        Returns
        -------
        str
            Will return the filename generated
        '''

        srcdir = '.cache/client/'
        destzip = cls.config['exportprefix'] + '-' + datetime.datetime.now().strftime('%Y%m%d') + '-update.zip'
        check = datetime.datetime.now().timestamp() - (86400 * cls.config['updatedays'])
        ziptarget = os.path.join(cls.config['exportdir'], destzip)
        with zipfile.ZipFile(ziptarget, 'w') as zip:
            for k in cls.installed:
                if cls.installed[k]['updated'] >= check and k != 'BepInExPack_Valheim':
                    for root, dirs, files in os.walk(os.path.join(srcdir, 'BepInEx', 'plugins', k)):
                        for f in files:
                            p = os.path.join(root, f)
                            zip.write(p, arcname=p[len(srcdir):])
        
        return ziptarget
    
    @classmethod
    def export_changelog(cls) -> str:
        '''
        Export a list of changes in this deployment

        Returns
        -------
        str
            Will return the filename generated
        '''
        installs = []
        updates = []
        removes = []
        uuids = cls.changed.keys()
        packages = cls.get_by_uuids(uuids)

        for pkg in packages:
            change = cls.changed[pkg.uuid]

            if change['old'] == change['new']:
                # Changes recorded, but must have already been rolled back
                continue
            elif change['old'] is None:
                # New record
                installs.append('Installed ' + pkg.name + ' ' + pkg.installed_version)
            elif change['new'] is None:
                # Removed record
                removes.append('Removed ' + pkg.name + ' ' + change['old'])
            else:
                # Updated
                updates.append('Updated ' + pkg.name + ' from ' + change['old'] + ' to ' + change['new'])
        
        if len(installs) > 0 or len(updates) > 0 or len(removes) > 0:
            changes = '## ' + cls.config['exportprefix'] + ' ' + datetime.datetime.now().strftime('%Y-%m-%d') + '\n\n'

            if len(installs) > 0:
                changes += '*' + '\n*'.join(installs)
            
            if len(updates) > 0:
                changes += '*' + '\n*'.join(updates)
            
            if len(removes) > 0:
                changes += '*' + '\n*'.join(removes)
            
            changes += '\n\n'
        
            mdtarget = os.path.join(cls.config['exportdir'], 'CHANGELOG.md')
            try:
                with open(mdtarget, 'r') as f:
                    changelog = f.read()
            except FileNotFoundError:
                changelog = ''
            
            with open(mdtarget, 'w') as f:
                f.write(changes + changelog)
            
            return mdtarget
        else:
            return ''
    
    @classmethod
    def export_modlist(cls) -> str:
        '''
        Export a list of all mods installed

        Returns
        -------
        str
            Will return the filename generated
        '''

        mdtarget = os.path.join(cls.config['exportdir'], 'MODS.md')
        with open(mdtarget, 'w') as f:
            f.write('# Mods Included\n\n')
            for pkg in cls.get_installed_packages():
                f.write('* ' + pkg.name + ' ' + pkg.installed_version + '\n')

        return mdtarget

    @classmethod
    def commit_changes(cls):
        '''
        Mark everything as deployed and remove the pending caches
        '''
        if os.path.exists('.cache/changed.json'):
            os.remove('.cache/changed.json')
        
        if os.path.exists('.cache/removed.json'):
            os.remove('.cache/removed.json')
        
        cls.changed = {}
        cls.removed = []


#!/usr/bin/env python3

import math
import os
from manager import ModPackages
from pprint import pprint

ModPackages.init()

def _menu(title: str, options: list, quit: bool = False, clear: bool = False, back: bool = False, default = None):
    if clear:
        os.system('clear')
    
    print(title + '\n')
    
    space = math.floor(math.log10(len(options))) + 1
    
    c = 0
    for i in options:
        c += 1
        s = space - math.floor(math.log10(c))
        print(str(c) + ':' + (' ' * s) + i[0])
    
    if back:
        print('B: Go Back')
    
    if quit:
        print('Q: Quit Application')
    
    print('')
    opt = input('Enter 1-' + str(len(options)) + ': ')

    if opt == '':
        opt = default

    if quit and opt is not None and opt.lower() == 'q':
        print('Bye bye')
        exit()
    
    if back and opt is not None and opt.lower() == 'b':
        return None
    
    if clear:
        os.system('clear')
    else:
        print('')
    
    c = 0
    sel = None
    for i in options:
        c += 1
        if opt == str(c):
            sel = i[1]
    
    if hasattr(sel, '__call__'):
        return sel()
    else:
        return sel
        

def _wait():
    print('')
    input('Press ENTER to continue')

def menu_main():
    run = _menu(
        'Valheim Mod Manager',
        (
            ('List Mods Installed', list_installed),
            ('Install New Mod', install_new),
            ('Check For Updates', check_updates),
            ('Uninstall Mod', remove),
            ('Revert Modifications', rollback),
            #('Sync Game Mods       [Local Game]', sync_game),
            #('Import Game Mods     [Local Game]', import_existing),
            ('Export/Package Mods', export_package)
        ),
        quit=True, clear=True
    )

    if run == 'wait':
        _wait()

def check_environment():
    '''
    Check the environment on starting to allow the user to sync existing mods easily
    '''
    print('Checking local game environment...')
    mods = []
    diff = False
    game = ModPackages.get_synced_packages()
    for pkg in game:
        if pkg.installed_version is None:
            # Mod in game directory is not registered as installed
            print(pkg.name + ' found in game but is not registered yet')
            diff = True
        elif pkg.installed_version != pkg.selected_version:
            # Mod installed, but versions differ
            print(pkg.name + ' ' + pkg.selected_version + ' found in game directory differs from registered version')
            diff = True
        
        mods.append(pkg.name)
    local = ModPackages.get_installed_packages()
    for pkg in local:
        # Skip auto-generated system mods
        if pkg.name == 'BepInExPack_Valheim' or pkg.name == 'HookGenPatcher':
            continue
            
        if pkg.name not in mods:
            print(pkg.name + ' registered but is not installed in game yet')
            diff = True
    
    if diff:
        _menu(
            title='Changes detected',
            options=(
                ('Sync changes', import_existing),
                ('Continue without syncing', 'skip')
            ),
            default='1'
        )

def list_installed() -> str:
    print('Installed Mods')
    print('')
    changes = False
    for pkg in ModPackages.get_installed_packages():
        print('* ' + pkg.name + ' ' + pkg.installed_version)
        changes = True
    
    if not changes:
        print('No mods are installed!  Try running "Import Game Mods" to import your existing mods or "Install New Mod" to start!')
    
    return 'wait'

def sync_game() -> str:
    print('Syncing game client...')
    ModPackages.sync_game()
    return 'wait'

def install_new():
    print('Install New Mod')
    print('')
    opt = input('Enter the mod name or URL to install (or ENTER to return): ')

    if opt == '':
        return

    mod = None
    mods = ModPackages.search(opt)
    if len(mods) == 0:
        print('No mods found!')
        _wait()
        return install_new()
    elif len(mods) > 1:
        mods.sort(reverse=True, key=lambda mod: mod.rating)
        opts = []
        for m in mods:
            opts.append((m.name + ' by ' + m.owner + ' last updated ' + m.update.strftime('%Y-%m-%d'), m))
        opt = _menu(title='Multiple mods found', options=opts, back=True, default='b')

        if opt is None:
            return install_new()
        else:
            mod = opt
    else:
        mod = mods[0]
    
    opts = []
    for v in mod.versions:
        opts.append((v.version + ' released ' + v.created.strftime('%Y-%m-%d'), v))
    
    vers = _menu(title='Select Version (or ENTER to auto select newest)', options=opts, back=True, default='1')

    if vers is None:
        return
    
    mod.selected_version = vers.version
    print('Installing ' + mod.name + ' v' + vers.version)
    print(vers.description)
    print('')

    try:
        opt = input('ENTER to resume, CTRL+C to stop: ')
    except KeyboardInterrupt:
        opt = 'n'
    
    if opt == '':
        mod.install()
        ModPackages.sync_game()
        print('Mod installed')
        return 'wait'
    else:
        print('not installing')

def export_package():
    print('Exporting mod packages...')
    full = ModPackages.export_full()
    updates = ModPackages.export_updates()
    changelog = ModPackages.export_changelog()
    modlist = ModPackages.export_modlist()

    ModPackages.commit_changes()

    print('Created bundles:')
    print('Full:      ' + full)
    print('Updates:   ' + updates)
    print('Changelog: ' + changelog)
    print('Modlist:   ' + modlist)
    return 'wait'

def check_updates() -> str:
    print('Checking for updates...')
    print('')
    updates_available = False
    opts = []
    opts.append(('Install all updates', 'ALL'))
    for pkg in ModPackages.get_installed_packages():
        updates = pkg.check_update_available()
        v1 = pkg.get_installed_version().version
        v2 = pkg.get_highest_version().version

        if updates:
            opts.append((pkg.name + ' ' + v1 + ' update available to ' + v2, pkg))
            updates_available = True
    
    if not updates_available:
        print('No mod updates are available!')
        return 'wait'
    
    opt = _menu(title='Select an update to perform or ENTER to update all', options=opts, default='1', back=True)
    
    if opt is None:
        # User opted to not perform any updates
        return
    elif opt == 'ALL':
        # User opted to perform ALL updates
        for pkg in ModPackages.get_installed_packages():
            if pkg.check_update_available():
                pkg.upgrade()
                print('Updated ' + pkg.name)
        ModPackages.sync_game()
    else:
        # Specific package to update
        opt.upgrade()
        ModPackages.sync_game()
        print('Updated ' + opt.name)

    return 'wait'

def rollback() -> str:
    print('Checking for changes...')
    print('')
    updates_available = False
    opts = []
    pkgs = []
    opts.append(('Rollback everything', 'ALL'))
    for pkg in ModPackages.get_installed_packages():
        try:
            changes = ModPackages.changed[pkg.uuid]

            if changes['old'] == changes['new']:
                # Changes recorded, but must have already been rolled back
                continue
            elif changes['old'] is None:
                # New record
                opts.append(('Remove ' + pkg.name + ' ' + pkg.installed_version, pkg))
                pkgs.append(pkg)
                updates_available = True
            elif changes['new'] is None:
                # Removed record
                opts.append(('Reinstall ' + pkg.name + ' ' + changes['old'], pkg))
                pkgs.append(pkg)
                updates_available = True
            else:
                # Updated
                opts.append(('Revert ' + pkg.name + ' from ' + changes['new'] + ' to ' + changes['old'], pkg))
                pkgs.append(pkg)
                updates_available = True
        except KeyError:
            # No changes recorded, nothing to perform
            pass
    
    if not updates_available:
        print('No changes found')
        return 'wait'
    
    opt = _menu(title='Select an update to revert or ENTER to rollback everything', options=opts, default='1', back=True)
    
    if opt is None:
        # User opted to not perform any updates
        return
    elif opt == 'ALL':
        # User opted to perform ALL updates
        for pkg in pkgs:
            pkg.rollback()
            print('Reverted ' + pkg.name)
        ModPackages.sync_game()
    else:
        # Specific package to update
        opt.rollback()
        ModPackages.sync_game()
        print('Reverted ' + opt.name)

    return 'wait'

def remove() -> str:
    pkgs = ModPackages.get_installed_packages()
    opts = []
    c = -1
    for pkg in pkgs:
        c += 1
        opts.append((pkg.name + ' ' + pkg.installed_version, c))
    
    opt = _menu(title='Uninstalling Mod', options=opts, back=True, default='b')

    if opt is None:
        return
    
    pkgs[opt].remove()
    ModPackages.sync_game()
    print('Selected mod has been removed')
    return 'wait'

def import_existing() -> str:
    print('Scanning for current packages...')
    packages = ModPackages.get_synced_packages()

    check = []
    dupes = []
    for p in packages:
        if p.name in check and p.name not in dupes:
            dupes.append(p.name)
        else:
            check.append(p.name)
    
    if len(dupes) > 0:
        # The manifest doesn't contain all data to uniquely identify the source package,
        # and some authors will fork projects to publish under the same name.
        for d in dupes:
            opts = []
            for p in packages:
                if p.name == d:
                    opts.append((p.name + ' by ' + p.owner + ' last updated ' + p.update.strftime('%Y-%m-%d'), p))
            opt = _menu(title='Duplicates found for package, please select the one to install', options=opts)

            # Since we can't modify a list while iterating over, (and modifying it will change the keys),
            # create a copy list and copy valid entries over
            p1 = []
            for p in packages:
                if p.name != d or p == opt:
                    p1.append(p)
            packages = p1

    print('')
    for p in packages:
        print('* ' + p.name + ' ' + p.selected_version)
    
    try:
        opt = input('ENTER to load current mods, CTRL+C to stop: ')
    except KeyboardInterrupt:
        opt = 'n'
    
    if opt == '':
        for p in packages:
            print('Installing ' + p.name + ' ' + p.selected_version + '...')
            p.install()

        return 'wait'

# MaGic-Quick_Deposit-1.0.1

#pprint(packages.packages[50].__dict__)
#pprint(packages.packages[50].versions[0].__dict__)

#pprint(packages.search('Quick_Deposit'))
#pprint(packages.search('https://valheim.thunderstore.io/package/OdinPlus/BoomStick/')[0].__dict__)

#p = ModPackages.search('https://valheim.thunderstore.io/package/OdinPlus/BoomStick/')[0]
#for v in p.versions:
#    pprint(v.__dict__)
#p.install()

#ModPackages.export_full()

#ModPackages.export_updates()

#pprint(ModPackages.packages[60].check_update_available())


check_environment()

while True:
    menu_main()

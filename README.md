# Requiem-Converter
A local web UI for converting and transferring RE Engine game saves between PC (Steam) and Jailbroken PS5. Integrates MandarinJuice, a Garlic-compatible package builder, and a hex patch editor, no external tools needed. (Vibecoded and only tested with PC Save games converted to Jailbroken PS5)

Requirements
Python 3.8+
.NET 10.0 runtime (apt install dotnet10 on Ubuntu 24.04, or from dot.net)
Garlic running on your PS5 (for PS5 push)




Setup


```
git clone https://github.com/Yqno/Requiem-Converter/
cd Requiem-Converter
python3 server.py

```
Enter your ID and garlic IP adress in the ```server.py``` and then Open ```http://localhost:8765``` in your browser.



The MandarinJuice binary and convert_re9_ps5 binary must be in the same directory as server.py. Game profiles go in _profiles/.

Features
Convert (PC → PS5 / PS5 → PC)

Converts saves using the convert_re9_ps5 binary.

Confirmed working: Resident Evil 9 Requiem

Inspect

Reads and displays internal save fields: _MainRegionHash, _ApplicationVersion, User ID, and magic header. Useful for verifying a save before and after conversion.

MandarinJuice

Decrypt, encrypt, brute-force, and re-sign RE Engine saves using MandarinJuice v1.4.1+ by @Mi5hmasH.

Brute Force — finds the Steam ID embedded in an encrypted save
Re-Sign — replaces one User ID with another (e.g. Steam ID → PS5 Account ID)

Supported games and profiles via MandarinJuice:

Game	Status
Resident Evil 9 Requiem (Steam + Epic)	
Resident Evil 9 Requiem Demo (Steam + Epic)	
Monster Hunter Wilds
Dragon's Dogma 2	
Dead Rising Deluxe Remaster
Kunitsu-Gami: Path of the Goddess	
Monster Hunter Stories 3	
Mega Man Star Force Legacy Collection	
Onimusha: Way of the Sword (Steam + Epic)	
PRAGMATA

 MandarinJuice can brute-force and re-sign the save, but full PS5 compatibility (region hash, app version fields) has not been verified. 
 Only Tested with RE Requiem which works Fine
```
Save Editor
Garlic ZIP Import, drag in a Garlic backup ZIP, extracts all .bin saves automatically
Hex Patch, patch any uint32 field in a save file (find → replace). Includes presets for RE9 region hash and app version values
Python Brute Force, Steam ID brute-forcer implemented in Python as a fallback
Garlic Package
```

Builds a Garlic-compatible folder structure from one or more .bin saves. Use this to import saves into Garlic Save Manager on the PS5.
```
PS5 Push

Sends a save directly to the PS5 over HTTP via Garlic's save service API (/api/savedata). Requires Garlic running and the PS5 on the same network.

Workflow: RE9 PC → PS5

MandarinJuice → Brute Force your original PC save to find the Steam ID

Convert tab → PC to PS5 (or use MandarinJuice Re-Sign with your PS5 Account ID)

Hex Patch → apply region preset for your PS5 version (EU/AS or EU/US) and PS5 app version

Garlic Package → build the package with Title ID PPSA31246 (EU) or your region's ID

PS5 Push → send to PS5, or use Garlic Save Manager manually

Known Values (RE9 EU)

Field	Value

_MainRegionHash PC	1874947740

_MainRegionHash PS5 EU/AS	481759118

_MainRegionHash PS5 EU/US	3208943443

_ApplicationVersion PC	16781314

_ApplicationVersion PS5	16785408

Title ID EU	PPSA31246
```

Based on:

This tool ships with and is built around the following projects:


- [MandarinJuice](https://github.com/mi5hmash/MandarinJuice) by [Mi5hmasH](https://github.com/mi5hmash) — RE Engine save encryption, decryption, brute-force and re-signing. The `MandarinJuice` CLI binary and all game profiles in `_profiles/` are from this project.
- [garlic-savemgr](https://github.com/earthonion/garlic-savemgr) by [earthonion](https://github.com/earthonion) — PS5 save manager. The `sce_sys` template files (`keystone`, `param.sfo`, `icon0.png`) and the HTTP save push API are part of Garlic's format.
- [ree-save-editor](https://github.com/kvasszn/ree-save-editor) by [kvasszn](https://github.com/kvasszn) — open-source reference for RE Engine save structure and field layout.


The convert_re9_ps5 binary is a standalone RE9-specific converter built on top of the private ree_lib crate.

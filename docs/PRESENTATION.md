# Presentation — eSim Automated Tool Manager

Duration: about 2 minutes  
Video: [`docs/demo/esim_toolmanager_demo.mp4`](demo/esim_toolmanager_demo.mp4)

---

## Sequence

1. Title  
2. Problem  
3. Design (catalog, modules, backends)  
4. Capabilities  
5. Live demo  
   - `python -m pytest -q`  
   - `install demo-tool --force`  
   - `status demo-tool`  
   - `plan ngspice` (Windows: portable archive, no admin)  
   - `plan kicad` (Windows: adopt if present, else print plan — no UAC)  
   - `update --check`  
   - `configure demo-tool`  
   - `deps demo-tool`  
   - `list`  
   - `verify`  
   - GUI  
6. Repository paths  

---

Design: `docs/DESIGN.md` · Run: `README.md` · Code: `esim_toolmanager/`

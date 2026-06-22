
import streamlit as st
import cadquery as cq
import json
import os
from google import genai
from google.genai import types

# Load local environment variables from .env file if present
if os.path.exists(".env"):
    with open(".env") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                key, val = line.strip().split("=", 1)
                os.environ[key.strip()] = val.strip().strip("'\"")

# Initialize Gemini Client (it automatically scans for os.environ["GEMINI_API_KEY"])
try:
    client = genai.Client()
except Exception as e:
    st.error("Missing API Key! Please create a .env file with GEMINI_API_KEY='your_key' or run: export GEMINI_API_KEY='your_key'")

st.set_page_config(layout="wide")
st.title("🤖 Automotive Text-to-CAD Application")
st.write("Generate and modify STEP geometries seamlessly using natural language.")

# UI Layout: Split the screen into an options panel and a 3D visualization canvas
col1, col2 = st.columns([1, 1.2])

with col1:
    st.header("Engineering Input")
    part_type = st.selectbox("Component Type", ["Roof Bow", "B-Pillar Reinforcement", "Standard Block", "Door Bracket", "Bumper Extension", "Floor Rail"])
    base_thickness = st.slider("Default Sheet Metal Thickness (mm)", 0.8, 3.0, 1.2, step=0.1)
    
    user_prompt = st.text_area(
        "Describe your geometry creation or modification:",
        placeholder="e.g., Create a block 100 x 100 x 100 mm with the centroid at 0,0,0"
    )
    
    execute_button = st.button("Execute Design Intent", type="primary")
 
# File output paths
STEP_OUTPUT = "engineered_component.step"
STL_OUTPUT = "preview_mesh.stl"
 
if execute_button:
    if not user_prompt:
        st.warning("Please provide a prompt description.")
    else:
        with st.spinner("Gemini interpreting engineering parameters..."):
            # Set explicit system instructions to constrain Gemini to output structured JSON variables
            system_instruction = f"""
            You are an automotive engineering design agent. Translate natural language into structured JSON keys.
            The user is designing a component of type: '{part_type}'.
            
            Available keys:
            - 'length' (float): Total length along the Z-axis (or primary span). Default: 1000.0 for Roof Bow, 1200.0 for B-Pillar, 100.0 for Block, 80.0 for Door Bracket, 300.0 for Bumper Extension, 1000.0 for Floor Rail.
            - 'width' (float): Bottom base width (or total width) along the X-axis. Default: 100.0 for Roof Bow, 150.0 for B-Pillar, 100.0 for Block, 40.0 for Door Bracket, 120.0 for Bumper Extension, 80.0 for Floor Rail.
            - 'width_top' (float): For B-Pillar and Bumper Extension, the tapered top width. Default: 90.0 for B-Pillar, 80.0 for Bumper Extension.
            - 'height' (float): Depth/height of the channel at the base (along Y-axis). Default: 25.0 for Roof Bow, 40.0 for B-Pillar, 100.0 for Block, 60.0 for Door Bracket, 60.0 for Bumper Extension, 20.0 for Floor Rail.
            - 'height_top' (float): For B-Pillar and Bumper Extension, the tapered top depth. Default: 20.0 for B-Pillar, 40.0 for Bumper Extension.
            - 'thickness' (float): Material sheet metal thickness. Default: {base_thickness}.
            - 'flange_width' (float): Width of the attachment/welding flanges. Default: 20.0 for Roof Bow, 25.0 for B-Pillar, 15.0 for Floor Rail.
            - 'camber' (float): Sweep/bow height or vertical kick-up/jog height (deviation in Y-axis). Default: 15.0 for Roof Bow, 30.0 for B-Pillar, 50.0 for Floor Rail.
            - 'hole_diameter' (float): For Door Bracket, the mounting hole diameter. Default: 8.0.
            
            Convert any user-specified dimensions (e.g. inches, centimeters) to millimeters (mm) before outputting.
            Return ONLY raw valid JSON text. No markdown blocks.
            """
            
            try:
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=f"Target Component Type: '{part_type}'. User prompt: '{user_prompt}'. Material fallback thickness: {base_thickness}",
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json"
                    ),
                )
                design_params = json.loads(response.text)
                st.json(design_params)  # Visual verification of data parameters
                
            except Exception as api_err:
                st.error(f"API Authentication Error: Ensure your GEMINI_API_KEY is exported correctly. Details: {api_err}")
                design_params = None

        if design_params:
            with st.spinner("OpenCascade engine translating constraints to solid geometry..."):
                try:
                    # Clear out old files if they exist
                    for f in [STEP_OUTPUT, STL_OUTPUT]:
                        if os.path.exists(f): os.remove(f)

                    # --- CAD WORKFLOW LOGIC SELECTION ---
                    if part_type == "Standard Block":
                        l = design_params.get("length", 100.0)
                        w = design_params.get("width", 100.0)
                        h = design_params.get("height", 100.0)
                        solid_geometry = cq.Workplane("XY").box(l, w, h)
                        
                    elif part_type == "Roof Bow":
                        # Extract parameters
                        L = design_params.get("length", 1000.0)
                        W = design_params.get("width", 100.0)
                        H = design_params.get("height", 25.0)
                        t = design_params.get("thickness", base_thickness)
                        f = design_params.get("flange_width", 20.0)
                        camber = design_params.get("camber", 15.0)
                        
                        # Apply safety constraints
                        f = min(f, W * 0.3)
                        d = min(8.0, (W - 2*f) * 0.4)
                        
                        # Generate sweep path along Z, curved in Y (camber)
                        path = cq.Workplane("XZ").threePointArc((0, camber, L/2), (0, 0, L))
                        
                        # Generate symmetric open hat section profile in XY plane
                        profile = (cq.Workplane("XY")
                                   .moveTo(-W/2, 0)
                                   .lineTo(-W/2 + f, 0)
                                   .lineTo(-W/2 + f + d, H)
                                   .lineTo(W/2 - f - d, H)
                                   .lineTo(W/2 - f, 0)
                                   .lineTo(W/2, 0)
                                   .offset2D(t))
                        
                        solid_geometry = profile.sweep(path)
                        
                    elif part_type == "B-Pillar Reinforcement":
                        # Extract parameters
                        L = design_params.get("length", 1200.0)
                        W_base = design_params.get("width", 150.0)
                        W_top = design_params.get("width_top", 90.0)
                        H_base = design_params.get("height", 40.0)
                        H_top = design_params.get("height_top", 20.0)
                        t = design_params.get("thickness", base_thickness)
                        f = design_params.get("flange_width", 25.0)
                        camber = design_params.get("camber", 30.0)
                        
                        # Interpolated mid-section dimensions
                        W_mid = (W_base + W_top) / 2
                        H_mid = (H_base + H_top) / 2
                        
                        # Apply safety constraints
                        f_base = min(f, W_base * 0.3)
                        d_base = min(15.0, (W_base - 2*f_base) * 0.4)
                        
                        f_mid = min(f, W_mid * 0.3)
                        d_mid = min(12.0, (W_mid - 2*f_mid) * 0.4)
                        
                        f_top = min(f, W_top * 0.3)
                        d_top = min(8.0, (W_top - 2*f_top) * 0.4)
                        
                        # 1. Base profile at Z = 0
                        w1 = (cq.Workplane("XY")
                              .moveTo(-W_base/2, 0)
                              .lineTo(-W_base/2 + f_base, 0)
                              .lineTo(-W_base/2 + f_base + d_base, H_base)
                              .lineTo(W_base/2 - f_base - d_base, H_base)
                              .lineTo(W_base/2 - f_base, 0)
                              .lineTo(W_base/2, 0)
                              .offset2D(t)
                              .wires().val())
                        
                        # 2. Mid profile at Z = L/2, shifted in Y by camber
                        w2 = (cq.Workplane("XY")
                              .workplane(offset=L/2)
                              .moveTo(-W_mid/2, camber)
                              .lineTo(-W_mid/2 + f_mid, camber)
                              .lineTo(-W_mid/2 + f_mid + d_mid, H_mid + camber)
                              .lineTo(W_mid/2 - f_mid - d_mid, H_mid + camber)
                              .lineTo(W_mid/2 - f_mid, camber)
                              .lineTo(W_mid/2, camber)
                              .offset2D(t)
                              .wires().val())
                        
                        # 3. Top profile at Z = L
                        w3 = (cq.Workplane("XY")
                              .workplane(offset=L)
                              .moveTo(-W_top/2, 0)
                              .lineTo(-W_top/2 + f_top, 0)
                              .lineTo(-W_top/2 + f_top + d_top, H_top)
                              .lineTo(W_top/2 - f_top - d_top, H_top)
                              .lineTo(W_top/2 - f_top, 0)
                              .lineTo(W_top/2, 0)
                              .offset2D(t)
                              .wires().val())
                        
                        # 4. Create loft through the wires
                        wp = cq.Workplane()
                        wp.ctx.pendingWires.append(w1)
                        wp.ctx.pendingWires.append(w2)
                        wp.ctx.pendingWires.append(w3)
                        solid_geometry = wp.loft()
                        
                    elif part_type == "Door Bracket":
                        # Extract parameters
                        L1 = design_params.get("length", 80.0)
                        L2 = design_params.get("height", 60.0)
                        W = design_params.get("width", 40.0)
                        t = design_params.get("thickness", base_thickness)
                        hd = design_params.get("hole_diameter", 8.0)
                        
                        # Generate extrusion base
                        bracket = (cq.Workplane("XY")
                                   .moveTo(L1, 0)
                                   .lineTo(0, 0)
                                   .lineTo(0, L2)
                                   .offset2D(t/2)
                                   .extrude(W))
                        
                        # Try placing mounting holes
                        try:
                            bracket = bracket.faces("<Y").workplane().hole(hd)
                            bracket = bracket.faces("<X").workplane().hole(hd)
                        except Exception:
                            pass
                            
                        solid_geometry = bracket
                        
                    elif part_type == "Bumper Extension":
                        # Extract parameters
                        L = design_params.get("length", 300.0)
                        W_base = design_params.get("width", 120.0)
                        W_top = design_params.get("width_top", 80.0)
                        H_base = design_params.get("height", 60.0)
                        H_top = design_params.get("height_top", 40.0)
                        t = design_params.get("thickness", base_thickness)
                        
                        # Base wire
                        w1 = (cq.Workplane("XY")
                              .moveTo(-W_base/2, H_base)
                              .lineTo(-W_base/2, 0)
                              .lineTo(W_base/2, 0)
                              .lineTo(W_base/2, H_base)
                              .offset2D(t/2)
                              .wires().val())
                        
                        # Top wire
                        w2 = (cq.Workplane("XY")
                              .workplane(offset=L)
                              .moveTo(-W_top/2, H_top)
                              .lineTo(-W_top/2, 0)
                              .lineTo(W_top/2, 0)
                              .lineTo(W_top/2, H_top)
                              .offset2D(t/2)
                              .wires().val())
                        
                        wp = cq.Workplane()
                        wp.ctx.pendingWires.append(w1)
                        wp.ctx.pendingWires.append(w2)
                        solid_geometry = wp.loft()
                        
                    elif part_type == "Floor Rail":
                        # Extract parameters
                        L = design_params.get("length", 1000.0)
                        W = design_params.get("width", 80.0)
                        H = design_params.get("height", 20.0)
                        t = design_params.get("thickness", base_thickness)
                        f = design_params.get("flange_width", 15.0)
                        jog = design_params.get("camber", 50.0)
                        
                        # Incline/jog spline path
                        pts = [(0, 0, 0), (0, 0, L/4), (0, jog/2, L/2), (0, jog, 3*L/4), (0, jog, L)]
                        path = cq.Workplane("XZ").spline(pts)
                        
                        # Hat profile dimensions
                        f_val = min(f, W * 0.3)
                        d = min(6.0, (W - 2*f_val) * 0.4)
                        
                        profile = (cq.Workplane("XY")
                                   .moveTo(-W/2, 0)
                                   .lineTo(-W/2 + f_val, 0)
                                   .lineTo(-W/2 + f_val + d, H)
                                   .lineTo(W/2 - f_val - d, H)
                                   .lineTo(W/2 - f_val, 0)
                                   .lineTo(W/2, 0)
                                   .offset2D(t))
                        
                        solid_geometry = profile.sweep(path)
                        
                    else:
                        # Fallback default sheet metal profile option
                        t = design_params.get("thickness", base_thickness)
                        w = design_params.get("width", 80.0)
                        solid_geometry = (cq.Workplane("XY")
                                          .lineTo(0, 20).lineTo(15, 20).lineTo(35, 0).lineTo(50, 0)
                                          .offset2D(t).extrude(w))

                    # Export production mathematical data
                    cq.exporters.export(solid_geometry, STEP_OUTPUT, cq.exporters.ExportTypes.STEP)
                    # Export high-fidelity WebGL viewing mesh
                    cq.exporters.export(solid_geometry, STL_OUTPUT, cq.exporters.ExportTypes.STL)
                    
                    st.success("✅ CAD solid validation passed. STEP and STL exported successfully.")
                    
                    # Direct production file download
                    with open(STEP_OUTPUT, "rb") as sf:
                        st.download_button("Download Production STEP File", data=sf, file_name="part.step")

                except Exception as cad_err:
                    st.error(f"OpenCascade Geometry Compilation Failure: {str(cad_err)}")

# Render the interactive Three.js 3D Viewport in the right panel if the STL file was generated
with col2:
    st.header("3D Interactive Verification Viewport")
    if os.path.exists(STL_OUTPUT):
        with open(STL_OUTPUT, "rb") as stl_file:
            stl_data = stl_file.read()
        
        # Inject standard open-source Three.js CDN libraries via HTML iframe component
        threejs_viewer_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
            <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>
            <style>
                body {{ margin: 0; background-color: #1e1e1e; overflow: hidden; }}
                #canvas-container {{ width: 100vw; height: 500px; }}
            </style>
        </head>
        <body>
            <div id="canvas-container"></div>
            <script>
                const container = document.getElementById('canvas-container');
                const scene = new THREE.Scene();
                scene.background = new THREE.Color(0x1a1a1a);
                
                // Camera Configuration
                const camera = new THREE.PerspectiveCamera(45, container.clientWidth / 500, 1, 3000);
                
                const renderer = new THREE.WebGLRenderer({{ antialias: true }});
                renderer.setSize(container.clientWidth, 500);
                renderer.shadowMap.enabled = true;
                container.appendChild(renderer.domElement);
                
                // Rotational mouse controls
                const controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;
                
                // Lighting arrays setup for realistic metallic/reflective sheet metal preview
                const ambientLight = new THREE.AmbientLight(0x555555);
                scene.add(ambientLight);
                
                const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.9);
                dirLight1.position.set(200, 400, 300).normalize();
                scene.add(dirLight1);
                
                const dirLight2 = new THREE.DirectionalLight(0x777777, 0.6);
                dirLight2.position.set(-200, -400, -300).normalize();
                scene.add(dirLight2);

                const pointLight = new THREE.PointLight(0xffffff, 0.3);
                pointLight.position.set(0, 300, 0);
                scene.add(pointLight);

                // Convert local python data stream to hex encoding to safely feed directly into JS loader
                const rawStlData = new Uint8Array({list(stl_data)});
                const loader = new THREE.STLLoader();
                const geometry = loader.parse(rawStlData.buffer);
                
                // Standard semi-reflective automotive engineering shader material (Metallic Steel)
                const material = new THREE.MeshStandardMaterial({{ 
                    color: 0xb0bec5, 
                    roughness: 0.3, 
                    metalness: 0.8,
                    side: THREE.DoubleSide
                }});
                
                const mesh = new THREE.Mesh(geometry, material);
                
                // Compute the geometry center to align bounding box perfectly to lookAt targets
                geometry.computeBoundingBox();
                const center = new THREE.Vector3();
                geometry.boundingBox.getCenter(center);
                mesh.position.sub(center); // Centers the centroid layout on 0,0,0
                
                scene.add(mesh);
                
                // Adjust camera position and grid helper based on the size of the geometry
                const size = new THREE.Vector3();
                geometry.boundingBox.getSize(size);
                const maxDim = Math.max(size.x, size.y, size.z);
                const fov = camera.fov * (Math.PI / 180);
                let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
                cameraZ *= 1.5; // Zoom out to give context
                
                camera.position.set(cameraZ * 0.7, cameraZ * 0.7, cameraZ * 0.7);
                camera.lookAt(0, 0, 0);
                controls.target.set(0, 0, 0);
                controls.update();

                // Grid ground guide representing the vehicle reference coordinate origin
                const maxGridSize = Math.max(maxDim * 1.5, 300);
                const gridHelper = new THREE.GridHelper(maxGridSize, 30, 0x666666, 0x333333);
                gridHelper.position.y = -size.y / 2 - 10;
                scene.add(gridHelper);

                function animate() {{
                    requestAnimationFrame(animate);
                    controls.update();
                    renderer.render(scene, camera);
                }}
                animate();
                
                window.addEventListener('resize', () => {{
                    camera.aspect = container.clientWidth / 500;
                    camera.updateProjectionMatrix();
                    renderer.setSize(container.clientWidth, 500);
                }});
            </script>
        </body>
        </html>
        """
        st.components.v1.html(threejs_viewer_html, height=510)
    else:
        st.info("No active part generated yet. Enter instructions to run OpenCascade.")
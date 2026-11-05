---
name: urban-3d-gis
description: "Expert guidelines for 3D urban scene rendering, WebGL/Three.js/MapLibre performance, GIS spatial-coordinate rebasing, insolation/shadows, and memory lifecycle in urban planning applications. Use whenever developing, modifying, or optimizing 3D viewers, site models, and interactive master plans."
---

# Urban 3D GIS & Master-Planning Visualization

Specialized skill synthesizing best practices from `threejs-fundamentals`, `threejs-spatial-data`, and `threejs-performance`, specifically adapted for urban development generators and master planning.

---

## 1. Spatial Coordinate Rebasing (Precision in GIS & WebGL)

### The Jittering Problem
Real-world geographic and cadastral coordinates (WGS84, UTM, Russian MSK zones) use huge numbers (e.g., `X = 523456.78`, `Y = 6123456.89`). Passing these directly into WebGL causes vertex jittering and Z-fighting because GPU vertex shaders operate in single-precision 32-bit floats.

### Golden Rule: Local Origin Rebasing
1. **Compute Site Center / Anchor once** on data load:
   ```javascript
   // Local origin anchor (center of site bounding box)
   const siteOrigin = {
     x: (minX + maxX) / 2,
     y: 0,
     z: (minY + maxY) / 2
   };
   ```
2. **Transform at render boundaries**:
   - Render coordinate = `RealCoord - siteOrigin`.
   - Keep real-world coordinates in element metadata (`userData.realX`, `userData.realY`, `userData.cadastreId`).
   - Reverse transform for exports and measurement tools: `ExportCoord = RenderCoord + siteOrigin`.

---

## 2. Three.js Architecture & Memory Lifecycle

### Prevention of WebGL Context Loss & Leaks
When regenerating layout variants, re-running optimization, or switching scenarios, old 3D objects must be thoroughly disposed of:

```javascript
function disposeHierarchy(node) {
  if (!node) return;
  
  if (node.children) {
    while (node.children.length > 0) {
      disposeHierarchy(node.children[0]);
      node.remove(node.children[0]);
    }
  }

  if (node.geometry) {
    node.geometry.dispose();
  }

  if (node.material) {
    if (Array.isArray(node.material)) {
      node.material.forEach(mat => disposeMaterial(mat));
    } else {
      disposeMaterial(node.material);
    }
  }
}

function disposeMaterial(mat) {
  Object.keys(mat).forEach(prop => {
    if (mat[prop] && typeof mat[prop].dispose === 'function') {
      mat[prop].dispose();
    }
  });
  mat.dispose();
}
```

### Modern Animation Loop (r180+)
- Use `renderer.setAnimationLoop(animate)` instead of manual `requestAnimationFrame`.
- Use `THREE.Timer` instead of deprecated `THREE.Clock`:
  ```javascript
  const timer = new THREE.Timer();
  timer.connect(document); // pauses when browser tab is inactive
  
  function animate() {
    timer.update();
    const delta = timer.getDelta();
    controls.update();
    renderer.render(scene, camera);
  }
  renderer.setAnimationLoop(animate);
  ```

---

## 3. High-Performance Batching for Urban Blocks

### InstancedMesh for Building Sections
Master plans consist of repetitive typical residential sections (рядовые, угловые, башни).
- **Anti-pattern:** Creating 500 separate `THREE.Mesh` objects (causes 500 draw calls, lagging the UI).
- **Best Practice:** Group identical section types into `THREE.InstancedMesh`.
  ```javascript
  // Batch all 9-story standard sections together:
  const sectionGeometry = createSectionGeometry(length, width, height);
  const instancedBuildings = new THREE.InstancedMesh(sectionGeometry, sectionMaterial, count);
  instancedBuildings.castShadow = true;
  instancedBuildings.receiveShadow = true;

  const dummy = new THREE.Object3D();
  instances.forEach((inst, index) => {
    dummy.position.set(inst.x, inst.y, inst.z);
    dummy.rotation.y = inst.rotationY;
    dummy.updateMatrix();
    instancedBuildings.setMatrixAt(index, dummy.matrix);
  });
  instancedBuildings.instanceMatrix.needsUpdate = true;
  ```

---

## 4. Insolation & Sunlight Simulation

### Accurate Shadows for Master Planning
- Shadows are crucial for evaluating insolation (инсоляция по СанПиН) and courtyard shading.
- Use `THREE.DirectionalLight` simulating the sun at given azimuth $\alpha$ and altitude $\beta$:
  ```javascript
  function updateSunPosition(sunLight, azimuthDeg, altitudeDeg, distance = 300) {
    const phi = (90 - altitudeDeg) * (Math.PI / 180);
    const theta = (azimuthDeg + 180) * (Math.PI / 180);

    sunLight.position.x = distance * Math.sin(phi) * Math.sin(theta);
    sunLight.position.y = distance * Math.cos(phi);
    sunLight.position.z = distance * Math.sin(phi) * Math.cos(theta);
    sunLight.target.position.set(0, 0, 0);
  }
  ```
- **Shadow Camera Tuning:**
  - Set shadow camera bounds (`top`, `bottom`, `left`, `right`) tightly around the site bounding box.
  - Set `sunLight.shadow.bias = -0.0005` to eliminate shadow acne.
  - Set `renderer.shadowMap.type = THREE.PCFShadowMap` (standard soft shadow).

---

## 5. UI Picking & Interactive TEP Tooltips

When the user hovers over or clicks a building section in the 3D viewer:
1. Raycast against the building meshes.
2. If using `InstancedMesh`, get the `instanceId`:
   ```javascript
   const intersects = raycaster.intersectObject(instancedBuildings);
   if (intersects.length > 0) {
     const id = intersects[0].instanceId;
     const metadata = sectionMetadataList[id];
     showTEPTooltip(metadata); // Floors, GFA, Living Area, Flats
   }
   ```
3. Avoid triggering full application reruns on hover; update an HTML HUD / overlay floating element.

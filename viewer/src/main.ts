import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { tileToWorld } from "./coords";

const MAP_SIZE = 32;

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1d2a1f);
const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 500);
camera.position.set(24, 28, 24);
const controls = new OrbitControls(camera, renderer.domElement);

scene.add(new THREE.HemisphereLight(0xffffff, 0x3a5a3a, 2));
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(MAP_SIZE, MAP_SIZE),
  new THREE.MeshLambertMaterial({ color: 0x6b8f4e }),
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground, new THREE.GridHelper(MAP_SIZE, MAP_SIZE, 0x2f3f2a, 0x4f6f3e));

const houseGeometry = new THREE.BoxGeometry(1, 1, 1);
const houseMaterial = new THREE.MeshLambertMaterial({ color: 0xb08850 });
for (const [tx, ty] of [[14, 14], [16, 15], [15, 17]] as const) {
  const { x, z } = tileToWorld(tx, ty, MAP_SIZE);
  const house = new THREE.Mesh(houseGeometry, houseMaterial);
  house.position.set(x, 0.5, z);
  scene.add(house);
}

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

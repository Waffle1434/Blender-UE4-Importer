[![discord](https://badgen.net/badge/icon/discord?icon=discord&label)](https://discord.gg/wUQKNu7dVQ)
# Blender UE4 Importer
Blender addon to import Unreal Engine 4 asset files. [Download the latest release](https://github.com/Waffle1434/Blender-UE4-Importer/releases/latest).

![image](https://github.com/Waffle1434/Blender-UE4-Importer/assets/8021358/cc2a6f1a-957f-47ad-8f1b-ccce553deb89)
![import_umesh](https://github.com/Waffle1434/Blender-UE4-Importer/assets/8021358/a46d7258-902c-45dc-8d0e-00f106bc34b0)

## Features
- Directly reads Unreal Engine project files, no exporting in Unreal Editor required
- Import full `.umap` scenes
- Import individual mesh & material `.uasset` files
- Pixel-perfect material recreation for supported nodes
- Blender equivalent material graph with labels and comments
- Cubemaps & irridance volume placement for Eevee
- [umodel.exe](https://www.gildor.org/en/projects/umodel) for texture extraction
- Normal map format correction

| Engine | UMap | Static Mesh | Skeletal Mesh | Material | Material Instance | Skeleton | Animation |
| :--- | :--: | :--: | :--: | :--: | :--: | :--: | :--: |
| 4.16 | ✔️ | ✔️ | ⚠️ | ✔️ | ✔️ | ❌ | ❌ |
| 4.27 | ✔️ | ✔️ | ⚠️ | ✔️ | ✔️ | ❌ | ❌ |
| 5 | ❓ | ❓ | ❓ | ❓ | ❓ | ❌ | ❌ |

## Known Issues
- Most testing has been performed on Unreal Engine 4.27 using free assets from the asset store. Unreal Engine 5 *might* work but its completely untested. If something isn't importing, I may be able to support it if you send a copy.
- Due to their complexity, materials are the most likely to fail to import. The importer will attempt to power through, but nodes may be missing or materials left unassigned.
- Skeletal meshes import as rigid meshes. I am *this* close to having skinning working, but I haven't figured out how to correctly correspond the vertex groups from the uasset.
- BSP and terrain is MIA, I may support this if requested enough.

## UMap Support
| Element | Support | Notes |
| :------ | :-----: | :---- |
| Static & Skeletal Meshes | ✔️ |
| Blueprint Instances | ⚠️ | Only Static Meshes for now |
| Point, Spot, Directional Lights | ✔️ | Eevee 128 light limit |
| Box & Sphere ReflectionCapture | ✔️ |
| Cameras | ✔️ |
| Material Overrides | ✔️ |
| Hierarchy Folders | ✔️ |
| BSP, Terrain | ❌ |

## Material Support
| Node | Support | Notes |
| :--- | :-----: | :---- |
| Add, Subtract, Multiply, Divide | ✔️ |
| Sin, Cos, Tan, Arcsin, Arccos, Arctan | ✔️ |
| Power, Log2, Log10 | ✔️ |
| Frac, Fmod, Round, Ceil, Floor, Truncate | ✔️ |
| Abs, Sign, 1-x, Min, Max | ✔️ |
| Step, Smoothstep, Clamp, Lerp | ✔️ |
| Distance, Dot, Cross, Normalize | ✔️ |
| Constants, Parameters | ✔️ |
| Switch, If | ✔️ |
| Texture2D (& Parameters), TextureCoordinate | ✔️ |
| TwoSidedSign, VertexColor, VertexNormal, WorldPosition, ObjectPosition | ✔️ |
| CameraPosition, CameraVector, CameraDepthFade | ✔️ |
| ScreenPosition, PixelDepth | ✔️ |
| Desaturation, Contrast, BlackBody | ✔️ |
| Append, ComponentMask | ⚠️ | vec1+vec1, TODO |
| MakeMaterialAttributes | ⚠️ | TODO: multiple nodes |
| Transform | ❌ | TODO |
| LightmassReplace | ❌ | N/A |
| Texture3D, BumpOffset, CustomExpression | ❌ | Blender unsupported |
| Material Functions | ✔️ |
| Comment, Reroute | ✔️ |

## Tested Assets
| Asset | Support | Notes |
| :---- | :-----: | :---- |
| [Modular SciFi Season 1 Starter Bundle](https://www.unrealengine.com/marketplace/en-US/product/modular-scifi-season-1-starter-bundle) | ✔️⚠️ | Parallax mapped snow, Blender unsupported |
| [Modular Scifi Season 2 Starter Bundle](https://www.unrealengine.com/marketplace/en-US/product/modular-scifi-season-2-starter-bundle) | ✔️ | Personal favorite |
| [FPS Weapons Bundle](https://www.unrealengine.com/marketplace/en-US/product/fps-weapon-bundle) | ✔️ |
| [Vehicle Variety Pack](https://www.unrealengine.com/marketplace/en-US/product/bbcb90a03f844edbb20c8b89ee16ea32) | ✔️ |
| [Vehicle Variety Pack Volume 2](https://www.unrealengine.com/marketplace/en-US/product/9a705589d1994c6e8757fdbedaf698af) | ✔️ |
| [Military Supplies - VOL.1 - Tents](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-1-tents) | ✔️ | $ |
| [Military Supplies - VOL.2 - Clothing](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-2-clothing-and-bags) | ✔️ | $ |
| [Military Supplies - VOL.3 - Checkpoint](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-3-security-checkpoint) | ✔️ | $ |
| [Military Supplies - VOL.4 - Furniture](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-4-furniture) | ✔️ | $ |
| [Military Supplies - VOL.5 - Devices](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-5-machines-and-devices) | ✔️⚠️ | $, Trailer materials swapped (*why*) |
| [Military Supplies - VOL.6 - Crates](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-6-crates) | ✔️ | $ |
| [Military Supplies - VOL.7 - Containers](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-7-containers) | ✔️ | $ |
| [Military Supplies - VOL.8 - Supplies](https://www.unrealengine.com/marketplace/en-US/product/military-supplies-vol-8-field-supplies) | ✔️ | $ |
| [Twinmotion Construction Vehicles 1](https://www.unrealengine.com/marketplace/en-US/product/twinmotion-construction-vehicles) | ❌ | Compressed (*fml*) |
| [Toolset Collection - Vol 1](https://www.unrealengine.com/marketplace/en-US/product/toolset-collection-vol-1) | ❌ | Compressed (*fml*) |

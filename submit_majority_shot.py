#!/usr/bin/env python3
import sys
import json
import time
import random
from urllib.request import Request, urlopen

def create_prompt(shot_num, prompt_text, ref_images=None, prefix=None):
    if prefix is None:
        prefix = f"majority_takes_effect/EP01_5090/EP01_Shot_{shot_num:02d}"
    
    nodes = {
        "2": {
            "class_type": "UNETLoader",
            "inputs": {
                "unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                "weight_dtype": "default"
            }
        },
        "3": {
            "class_type": "CLIPLoader",
            "inputs": {
                "clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                "type": "minimax",
                "device": "default"
            }
        },
        "4": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": "minimax_h3_video_vae_fp16.safetensors"
            }
        },
        "5": {
            "class_type": "VAELoader",
            "inputs": {
                "vae_name": "minimax_h3_audio_vae_fp32.safetensors"
            }
        },
        "10": {
            "class_type": "MiniMaxH3ReferenceToVideo",
            "inputs": {
                "clip": ["3", 0],
                "vae": ["4", 0],
                "audio_vae": ["5", 0],
                "prompt": prompt_text,
                "width": 640,
                "height": 1120,
                "length": 124,
                "ref_image_size": "match"
            }
        },
        "11": {
            "class_type": "RandomNoise",
            "inputs": {
                "noise_seed": random.randint(100000000, 999999999)
            }
        },
        "12": {
            "class_type": "BasicGuider",
            "inputs": {
                "model": ["2", 0],
                "conditioning": ["10", 0]
            }
        },
        "13": {
            "class_type": "KSamplerSelect",
            "inputs": {
                "sampler_name": "res_multistep"
            }
        },
        "14": {
            "class_type": "BasicScheduler",
            "inputs": {
                "model": ["2", 0],
                "scheduler": "simple",
                "steps": 20,
                "denoise": 1.0
            }
        },
        "15": {
            "class_type": "SamplerCustomAdvanced",
            "inputs": {
                "noise": ["11", 0],
                "guider": ["12", 0],
                "sampler": ["13", 0],
                "sigmas": ["14", 0],
                "latent_image": ["10", 1]
            }
        },
        "16": {
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["15", 0],
                "vae": ["4", 0]
            }
        },
        "17": {
            "class_type": "VAEDecodeAudio",
            "inputs": {
                "samples": ["15", 0],
                "vae": ["5", 0]
            }
        },
        "18": {
            "class_type": "CreateVideo",
            "inputs": {
                "images": ["16", 0],
                "audio": ["17", 0],
                "fps": 24.0,
                "bit_depth": 8
            }
        },
        "19": {
            "class_type": "SaveVideo",
            "inputs": {
                "video": ["18", 0],
                "filename_prefix": prefix,
                "format": "auto",
                "codec": "auto"
            }
        }
    }

    if ref_images:
        node_id_counter = 100
        for i, img_name in enumerate(ref_images):
            load_id = str(node_id_counter)
            nodes[load_id] = {
                "class_type": "LoadImage",
                "inputs": {"image": img_name}
            }
            nodes["10"]["inputs"][f"ref_images.ref_image_{i}"] = [load_id, 0]
            node_id_counter += 1

    return {"prompt": nodes, "client_id": f"majority_shot_{shot_num:02d}"}

def submit_and_wait(workflow_payload):
    req = Request(
        "http://127.0.0.1:8190/prompt",
        data=json.dumps(workflow_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urlopen(req, timeout=30) as resp:
        res = json.load(resp)
    prompt_id = res.get("prompt_id")
    print(f"SUBMITTED prompt_id={prompt_id}", flush=True)
    return prompt_id

def poll_job(prompt_id, timeout=600):
    start = time.time()
    print(f"POLLING_START prompt_id={prompt_id}", flush=True)
    while time.time() - start < timeout:
        time.sleep(4)
        try:
            with urlopen(f"http://127.0.0.1:8190/history/{prompt_id}", timeout=10) as resp:
                hist = json.load(resp)
                if prompt_id in hist:
                    outputs = hist[prompt_id].get("outputs", {})
                    print(f"COMPLETED prompt_id={prompt_id}", flush=True)
                    for node_id, out in outputs.items():
                        if "videos" in out:
                            for vid in out["videos"]:
                                print(f"OUTPUT_VIDEO: {vid.get('subfolder')}/{vid.get('filename')}", flush=True)
                    return True
        except Exception as e:
            pass
    print("TIMEOUT polling job", flush=True)
    return False

if __name__ == "__main__":
    shot_num = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    
    shots = {
        1: {
            "prompt": "9:16 竖屏短剧，电影质感，冷调未来共识广场。大远景慢推，中央百米巨型全息屏幕由暗骤然亮起，冰蓝荧光照亮潮湿沥青地面与数千市民剪影。屏幕滚动浮现英文与发光条纹。画外音冷静播报：“十日共识实验启动。未来十天，每晚由全球投票决定明日现实。”全息通电低频嗡鸣声。非叙事性音乐：N/A。",
            "refs": ["suye_ref.jpg"]
        },
        2: {
            "prompt": "图片1 锁定苏野的脸与做旧工装夹克。图片2 锁定哑银起子。9:16 竖屏短剧，高对比侧光。中近景侧俯拍，图片1 中的苏野单膝蹲在金属控制箱旁，右手握着图片2 的起子精准拧紧六角螺栓，面容冷峻。背景大屏冷光映在脸颊。画外音冷静播报：“第一日多数规则——说谎者失声。”金属拧转声。非叙事性音乐：N/A。",
            "refs": ["suye_ref.jpg", "terminal_prop_ref.jpg"]
        },
        3: {
            "prompt": "9:16 竖屏短剧，中景过肩。集市边缘，一名皮夹克商贩剧烈张大嘴唇叫卖，脖子青筋暴起，嘴型夸张却完全失声，神情瞬间转为极度恐慌；对面买家猛地一把夺回递出的智能手机抽身退后。警示灯红白交替闪烁，布料摩擦声，急促脚步声。非叙事性音乐：N/A。",
            "refs": ["suye_ref.jpg"]
        }
    }

    cfg = shots.get(shot_num)
    if not cfg:
        print(f"Shot {shot_num} not configured in demo map", flush=True)
        sys.exit(1)

    wf = create_prompt(shot_num, cfg["prompt"], cfg.get("refs"))
    pid = submit_and_wait(wf)
    poll_job(pid)

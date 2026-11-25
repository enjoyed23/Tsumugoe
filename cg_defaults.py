"""Default local CG graph and explicit bindings; no character content."""
import copy
GRAPH={
 'checkpoint':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':'waiIllustriousSDXL_v170.safetensors'}},
 'positive':{'class_type':'CLIPTextEncode','inputs':{'text':'','clip':['checkpoint',1]}},
 'negative':{'class_type':'CLIPTextEncode','inputs':{'text':'','clip':['checkpoint',1]}},
 'latent':{'class_type':'EmptyLatentImage','inputs':{'width':768,'height':432,'batch_size':1}},
 'sampler':{'class_type':'KSampler','inputs':{'model':['ipadapter',0],'positive':['positive',0],'negative':['negative',0],'latent_image':['latent',0],'seed':0,'steps':20,'cfg':5.0,'sampler_name':'euler','scheduler':'normal','denoise':1.0}},
 'decode':{'class_type':'VAEDecode','inputs':{'samples':['sampler',0],'vae':['checkpoint',2]}},
 'save':{'class_type':'SaveImage','inputs':{'images':['decode',0],'filename_prefix':'tsumugoe'}},
 'reference_image':{'class_type':'LoadImage','inputs':{'image':''}},
 'clip_vision':{'class_type':'CLIPVisionLoader','inputs':{'clip_name':'CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors'}},
 'ipadapter_model':{'class_type':'IPAdapterModelLoader','inputs':{'ipadapter_file':'ip-adapter-plus_sdxl_vit-h.safetensors'}},
 'ipadapter':{'class_type':'IPAdapterAdvanced','inputs':{'model':['checkpoint',0],'ipadapter':['ipadapter_model',0],'image':['reference_image',0],'clip_vision':['clip_vision',0],'weight':0.4,'weight_type':'linear','combine_embeds':'concat','start_at':0.0,'end_at':1.0,'embeds_scaling':'V only'}}}
DEFAULT={
 'endpoint':'http://127.0.0.1:8189','width':768,'height':432,'max_edge':1600,'max_pixels':1446400,'seed':-1,'timeout_seconds':600,'negative_prompt':'','workflow':GRAPH,
 'bindings':{'positive':['positive','text'],'negative':['negative','text'],'width':['latent','width'],'height':['latent','height'],'seed':['sampler','seed'],'output':'save','reference_image':['reference_image','image'],'adapter':'ipadapter','sampler':'sampler','model_source':['checkpoint',0],'clip_source':['checkpoint',1]},
 'sampler_cfg':7.0,'face_inpaint':{'enabled':True,'denoise':0.4},'ipadapter_settings':{'enabled':False,'weight':0.4,'weight_type':'linear','embeds_scaling':'V only'},
 'trigger_loras':{},
 'launcher':{'python':'C:/Users/PC_User/Downloads/StabilityMatrix-win-x64/Data/Packages/ComfyUI/venv/Scripts/python.exe','main':'C:/Users/PC_User/Downloads/StabilityMatrix-win-x64/Data/Packages/ComfyUI/main.py','models':'C:/Users/PC_User/Downloads/StabilityMatrix-win-x64/Data/Models','ipadapter':'C:/Users/PC_User/shichubo-studio/studio_v1/work/models/ipadapter','clip_vision':'C:/Users/PC_User/shichubo-studio/studio_v1/work/models/clip_vision'}}
def defaults():return copy.deepcopy(DEFAULT)


def is_standard(cfg):
 return cfg['workflow']==GRAPH and cfg['bindings']==DEFAULT['bindings']

"""Studio local face detector and mask/crop/composite nodes. No network calls."""
import os,sys,json,math
from pathlib import Path
root=Path(__file__).resolve().parents[3]/'face_runtime'
root.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,r'C:\Users\PC_User\shichubo-studio\studio_v1\work\face_runtime\site-packages')
os.environ['YOLO_CONFIG_DIR']=str(root/'settings')
os.environ['YOLO_OFFLINE']='true';os.environ['YOLO_AUTOINSTALL']='false'
os.environ['MPLCONFIGDIR']=str(root/'matplotlib')
import numpy as np,torch
from PIL import Image,ImageDraw,ImageFilter

def pil(image):return Image.fromarray(np.clip(image.detach().cpu().numpy()*255,0,255).astype(np.uint8))
def tensor(image):return torch.from_numpy(np.asarray(image,dtype=np.float32).copy()/255)
class StudioFaceDetect:
 @classmethod
 def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'model_path':('STRING',),'confidence':('FLOAT',{'default':.3,'min':0.,'max':1.})}}
 RETURN_TYPES=();FUNCTION='detect';CATEGORY='Studio/face';OUTPUT_NODE=True
 def detect(self,image,model_path,confidence):
  path=Path(model_path)
  if not path.is_file() or path.suffix.lower()!='.pt':raise ValueError('Local face detector model is missing')
  from ultralytics import YOLO,settings
  settings.update({'sync':False})
  # CPU keeps detection off the generation GPU; all model files must already exist.
  model=YOLO(str(path));result=model.predict(pil(image[0]),conf=confidence,device='cpu',verbose=False,save=False)[0]
  boxes=result.boxes.xyxy.cpu().tolist() if result.boxes is not None else []
  return {'ui':{'studio_face_boxes':boxes},'result':()}
class StudioFaceRegion:
 @classmethod
 def INPUT_TYPES(cls):return {'required':{'image':('IMAGE',),'box':('STRING',),'work_size':('INT',{'default':1024,'min':256,'max':2048,'step':8}),'margin':('FLOAT',{'default':.35,'min':0.,'max':2.})}}
 RETURN_TYPES=('IMAGE','MASK','STUDIO_FACE_REGION');FUNCTION='crop';CATEGORY='Studio/face'
 def crop(self,image,box,work_size,margin):
  source=pil(image[0]);width,height=source.size;x,y,z,t=map(float,json.loads(box));fw,fh=z-x,t-y
  if fw<=0 or fh<=0:raise ValueError('Face box has no area')
  left=max(0,math.floor(x-fw*margin));top=max(0,math.floor(y-fh*margin));right=min(width,math.ceil(z+fw*margin));bottom=min(height,math.ceil(t+fh*margin))
  w,h=right-left,bottom-top
  if min(w,h)<=0:raise ValueError('Face box is outside the image')
  scale=work_size/max(w,h);target=(max(8,round(w*scale/8)*8),max(8,round(h*scale/8)*8))
  mask=Image.new('L',(w,h));draw=ImageDraw.Draw(mask);draw.ellipse((x-left-fw*.08,y-top-fh*.08,z-left+fw*.08,t-top+fh*.08),fill=255)
  mask=mask.filter(ImageFilter.GaussianBlur(max(1,min(fw,fh)*.06)))
  crop=source.crop((left,top,right,bottom)).resize(target,Image.Resampling.LANCZOS)
  working_mask=mask.resize(target,Image.Resampling.BILINEAR)
  region={'left':left,'top':top,'width':w,'height':h,'mask':mask}
  return tensor(crop).unsqueeze(0),tensor(working_mask).unsqueeze(0),region
class StudioFacePaste:
 @classmethod
 def INPUT_TYPES(cls):return {'required':{'destination':('IMAGE',),'face':('IMAGE',),'region':('STUDIO_FACE_REGION',)}}
 RETURN_TYPES=('IMAGE',);FUNCTION='paste';CATEGORY='Studio/face'
 def paste(self,destination,face,region):
  image=pil(destination[0]);crop=pil(face[0]).resize((region['width'],region['height']),Image.Resampling.LANCZOS)
  image.paste(crop,(region['left'],region['top']),region['mask']);return (tensor(image).unsqueeze(0),)

class TsumugoeFacePass:
 @classmethod
 def INPUT_TYPES(cls):
  import comfy.samplers
  return {'required':{'image':('IMAGE',),'model':('MODEL',),'positive':('CONDITIONING',),'negative':('CONDITIONING',),'vae':('VAE',),'seed':('INT',{'default':0,'min':0,'max':2**64-1}),'steps':('INT',{'default':20,'min':1,'max':10000}),'cfg':('FLOAT',{'default':7.,'min':0.,'max':100.}),'sampler_name':(comfy.samplers.KSampler.SAMPLERS,),'scheduler':(comfy.samplers.KSampler.SCHEDULERS,),'denoise':('FLOAT',{'default':.4,'min':0.,'max':1.})}}
 RETURN_TYPES=('IMAGE',);FUNCTION='run';CATEGORY='Tsumugoe/face';OUTPUT_NODE=True
 def run(self,image,model,positive,negative,vae,seed,steps,cfg,sampler_name,scheduler,denoise):
  result=image;info={'status':'no_face','faces':0}
  try:
   from nodes import VAEEncode,VAEDecode,common_ksampler
   detector=r'C:\Users\PC_User\shichubo-studio\studio_v1\work\models\face_detection\face_yolov8n.pt'
   boxes=StudioFaceDetect().detect(image,detector,.3)['ui']['studio_face_boxes']
   for i,box in enumerate(boxes):
    crop,mask,region=StudioFaceRegion().crop(image,json.dumps(box),1024,.35)
    latent=VAEEncode().encode(vae,crop)[0];latent['noise_mask']=mask
    samples=common_ksampler(model,(seed+i+1)%(2**63),steps,cfg,sampler_name,scheduler,positive,negative,latent,denoise=denoise)[0]
    face=VAEDecode().decode(vae,samples)[0];result=StudioFacePaste().paste(result,face,region)[0]
   if boxes:info={'status':'completed','faces':len(boxes),'denoise':denoise}
  except Exception as e:
   # Cancellation must propagate; an interrupted job must never adopt an image.
   import comfy.model_management
   if isinstance(e,comfy.model_management.InterruptProcessingException):raise
   result=image;info={'status':'fallback','error':str(e)}
  return {'ui':{'tsumugoe_face':[info]},'result':(result,)}
NODE_CLASS_MAPPINGS={'TsumugoeFacePass':TsumugoeFacePass}
NODE_DISPLAY_NAME_MAPPINGS={'TsumugoeFacePass':'Tsumugoe: face inpaint (safe fallback)'}

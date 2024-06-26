import torch.multiprocessing as mp
from sklearn.model_selection import RandomizedSearchCV
from sklearn.neighbors import KNeighborsClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
import pandas as pd
import numpy as np
import os
import torch
import cv2
import pickle

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ["GLOG_minloglevel"] ="2"

venv = os.path.dirname((os.path.abspath(__file__)))

# --------------
# Funciones generales

def create_files(type: str):    
    equiv = {'graph':'mediapipe_landmarks','gradient':'hog_transform'}
    
    if type not in list(equiv.keys()):
        raise ValueError('Palabra clave no identificada.')
    else:
        func = equiv[type]
        path_py = f'{type}-processing/multiproc-{type}.py'
        path_ipynb = f'{type}-processing/modeller-{type}.ipynb'
        
        # Creación de archivo multiproc
        if os.path.exists(path_py):
            pass
        else:
            with open('samples\multiproc.txt','r') as file:
                commands = eval(file.read())
            with open(path_py, 'w') as file:
                file.write(commands)
        
        if os.path.exists(path_ipynb):
            pass
        else: 
            # Creación de archivo training
            with open('samples\modeller.txt','r') as file:
                commands = file.read()
            with open(path_ipynb,'w') as file:
                file.write(commands)
                        
def get_file_paths(folder_path):
    file_paths = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            file_paths.append(os.path.join(root, file))

    return file_paths

def retrieve_raw_paths():
    train = get_file_paths(venv + r'\synthetic-asl-alphabet\Train_Alphabet')
    test = get_file_paths(venv + r'\synthetic-asl-alphabet\Test_Alphabet')
    _all = [*train, *test]
    return train, test, _all

def dataset_exists():
    if os.path.exists(venv + r'\synthetic-asl-alphabet'):
        pass
    else:
        import opendatasets as od
        od.download("https://www.kaggle.com/datasets/lexset/synthetic-asl-alphabet",)

def load_model(keywords: dict):
    # keywords = {'tecnica': (graph,gradient,neural), 'modelo':(knn,rf,rn)}
    path = venv + f'{keywords["tecnica"]}-processing/{keywords["modelo"]}-model.pkl'
    with open(path,'rb') as file:
        model = pickle.load(file)
    return model

def select_lists(*args):
    valid = [lst for lst in args if isinstance(lst.multi_hand_landmarks,list)]
    
    if valid:
        return valid[0]
    else:
        return None

def dump_object(obj,filename):
    if os.path.exists(filename):
        with open(filename,'rb') as file:
            data = pickle.load(file)
        data.append(obj)
    else:
        data = [obj]
        
    with open(filename,'wb') as file:
        pickle.dump(data,file)

def show_CM(CM: pd.DataFrame,way='pandas-style'):
    if way=='pandas-style':
        stylish = CM.style.background_gradient(cmap='coolwarm').set_precision(2)
        return stylish
    elif way=='seaborn':
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        plt.figure(figsize=(10, 7))
        sns.heatmap(CM, annot=True, fmt="d", cmap="coolwarm")
        plt.title('Matriz de Confusión')
        plt.xlabel('Predicción')
        plt.ylabel('Actual')
        plt.show()
    else:
        raise AttributeError("'way' debe ser o 'pandas-style' (predeterminado) o 'seaborn'." )

# --------------
# Transformación de imágenes

class device_configuration:
    def __init__(self,preference: str = None):
        # Configura la unidad de procesamiento utilizada
        if preference is None:
            if torch.cuda.is_available():
                self.processing_unit = 'cuda:0'
                self.device = torch.device('cuda:0')
            else:
                self.processing_unit = 'cpu'
                self.device = torch.device('cpu')
        else:
            self.processing_unit = preference
            self.device = torch.device(preference)

        # Inicia la unidad de procesamiento para PyTorch
        torch.cuda.device(self.device)

        # Consolida como variable de interés los cores máximos
        if self.processing_unit=='cuda:0':
            self.max_cores = torch.cuda.get_device_properties(0).multi_processor_count
        else:
            self.max_cores = os.cpu_count()

class image_preprocessing:
    def __init__(self, image: str | np.ndarray, color: str = 'bgr'):
        if isinstance(image, str):    
            self.original_image = cv2.imread(image)
            self.image = cv2.imread(image)
            self.color = color
        elif isinstance(image, np.ndarray):
            self.original_image = image
            self.image = image
            self.color = color
        else:
            raise ValueError("No se pudo cargar la imagen.")
        
        self.size = self.image.shape
    
    def __to_self(func):
        def wrapper(self, *args, **kwargs):
            to_self = kwargs.pop('to_self', False) # Creo que es más intuitivo que to_self sea 'True' por defecto. Luego lo cambio
            result = func(self, *args, **kwargs)
            if to_self:
                self.image, self.color = result
                self.size = self.image.shape
            else:
                image, color = result
                new_instance = image_preprocessing(image=image,color=color)
                
                return new_instance
        return wrapper
    
    @__to_self
    def resize_image(self, pixels: int):
        resized_image = cv2.resize(self.image, (pixels, pixels))
        return resized_image, self.color
    
    @__to_self
    def to_grayscale(self):
        grayscale_image = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        return grayscale_image, 'gray'
        
    @__to_self
    def to_rgb(self):
        rgb_image = cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB)
        return rgb_image, 'rgb'
    
    @__to_self
    def blur_image(self):
        blurred_image = cv2.GaussianBlur(self.image,(7,7),0)
        return blurred_image, self.color    
    
    @__to_self
    def manual_adjust_luminosity(self,brightness: int = 0,contrast: int = 0):
        if brightness==0 and contrast==0:
            image = self.image
        else:
            if brightness != 0:
                if brightness > 0:
                    shadow = brightness
                    highlight = 255
                else:
                    shadow = 0
                    highlight = 255 + brightness
                
                alpha_b = (highlight - shadow) / 255
                image = cv2.addWeighted(self.image, alpha_b, self.image, 0, shadow)
            
            if contrast != 0:
                f = 131 * (contrast + 127) / (127 * (131 - contrast))
                alpha_c = f
                gamma_c = 127 * (1 - f)
                image = cv2.addWeighted(self.image, alpha_c, self.image, 0, gamma_c)
        
        return image, self.color
    
    @__to_self
    def auto_adjust_luminosity(self):
        gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        avg_bright = np.mean(gray)
        std_contrast = np.std(gray)
        
        brightness = int(128 - avg_bright)
        contrast = int((std_contrast / 64.0) * 127.0)
        
        im = self.manual_adjust_luminosity(brightness,contrast,to_self=False)
        return im.image, self.color
    
    def edge_detection(self):
        gray: image_preprocessing = self.to_grayscale(to_self=False)
        blurred: image_preprocessing = gray.blur_image(to_self=False)
        edges = cv2.Canny(blurred.image,50,150)
        return edges
        
    @__to_self
    def edge_enhancement(self,contrast: str = 'hard'):
        # Filtro de convolución de 3x3
        if contrast=='hard':
            kernel = np.array([[-1, -1, -1],
                               [-1, 10, -1],
                               [-1, -1, -1]])
        elif contrast=='soft':
            kernel = np.array([[0,-1,0],
                              [-1,5,-1],
                              [0,-1,0]])
        else:
            raise ValueError('Tipo de contraste no aceptado.')
        
        enhanced_image = cv2.filter2D(self.image, -1, kernel)
        return enhanced_image
        
    @__to_self
    def histogram_equalization(self,contrast: str = 'global'):
        if contrast=='global': # Solo Histogram Equalization
            return cv2.equalizeHist(self.image)
        elif contrast=='adaptive': # Adaptive Histogram Equalization
            eq = cv2.createCLAHE(clipLimit=40.0,tileGridSize=(8,8))
        elif contrast=='limited-adaptive': # Contrast Limited Adaptive Histogram Equalization
            eq = cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8))
        else:
            raise ValueError('Tipo de contraste no aceptado')
    
        equalized_image = eq.apply(self.image)
        return equalized_image
    
    def __find_hand_rectangle(self):
        # Detectar los bordes
        edges = self.edge_detection()
        
        # Buscar contornos y seleccionar el mayor
        contours, _ = cv2.findContours(edges,cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        largest_contour = max(contours, key=cv2.contourArea)
    
        # Crear el rectángulo de ajuste
        x, y, w, h = cv2.boundingRect(largest_contour)
    
        # Expandirlo para cubrir toda la palma (padding manualmente ajustable)
        padding = 5
        x = max(1, x - padding)
        y = max(1, y - padding)
        w = min(self.image.shape[1] - x, w + 2 * padding)
        h = min(self.image.shape[0] - y, h + 2 * padding)  
    
        # (X_POINT_START, Y_POINT_START, WIDTH, HEIGHT)
        return (x, y, w, h)
    
    @__to_self
    def segment_image(self):
        mask = np.zeros(self.image.shape[:2], np.uint8)
        
        bgm = np.zeros((1,65), np.float64)
        fgm = np.zeros((1,65), np.float64)

        rectangle = self.__find_hand_rectangle()
        
        cv2.grabCut(self.image, mask, rectangle, bgm, fgm, 20, cv2.GC_INIT_WITH_RECT)
        
        mask2 = np.where((mask == 2)|(mask == 0), 0, 1).astype('uint8')
        
        segmented = self.image * mask2[:,:,np.newaxis]
        
        return segmented, self.color

class mediapipe_landmarks(image_preprocessing):
    def __init__(self, image_path, color: str = 'bgr'):
        import mediapipe as mp
        super().__init__(image_path,color)
        self.image_path = image_path
        self.letter = self.image_path.split('\\')[-2]
        
        # Iniciar el framework de reconocimiento de coordenadas
        mp_hands = mp.solutions.hands
        hands = mp_hands.Hands(static_image_mode=True, max_num_hands=1, min_detection_confidence=0.5)
        mp_drawing = mp.solutions.drawing_utils

        # Leer y procesar la imagen
        self.to_rgb(to_self=True)
        
        
        image_rgb: image_preprocessing = self.to_rgb(to_self=False)
        
        results = select_lists(hands.process(image_rgb.image), hands.process(self.original_image))
        self.coords: np.array = np.empty((0, 2))

        # Si hay resultados para las imágenes        
        if results is not None:
            self.results: bool = True
            # Recuperar nodos de la imagen
            for hand_landmarks in results.multi_hand_landmarks:
                for idx, landmark in enumerate(hand_landmarks.landmark):
                    # Extraer las coordenadas y guardarlas en lista
                    h, w, c = self.image.shape
                    cx, cy = int(landmark.x * w), int(landmark.y * h)
                    self.coords = np.vstack((self.coords, np.array([cx, cy]).reshape(1, -1)))
                mp_drawing.draw_landmarks(self.image, hand_landmarks, mp_hands.HAND_CONNECTIONS)
        else:
            self.results: bool = False
            self.coords = np.zeros((21, 2))

        hands.close()
        
        self.__is_normalized: bool = False

    def visualize_landmarks(self):     
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 10))
        plt.imshow(self.image)
        plt.axis('off')  # Ocultar los ejes
        plt.show()
        
    def normalize_coords(self):
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        self.__is_normalized: bool = True
        self.coords = scaler.fit_transform(self.coords)
        
    def to_csv(self,normalize: bool = True):
        if normalize==True and self.__is_normalized==False:
            self.normalize_coords()
        else: pass
        
        coords = [self.image_path.split('\\')[-2]] + self.coords.flatten().tolist() + [self.image_path]
        
        columns = ['letra']
        for i in range(21):
            columns.extend([f"x_{i}", f"y_{i}"])
        columns += ['origen']

        ruta = venv + r'\graph-processing\processed_data\{}.csv'.format(self.image_path.split("\\")[-3])
        df = pd.DataFrame([coords],columns=columns)
        
        df.to_csv(ruta, index=True, mode='a', header=not os.path.exists(ruta))
        
    def extract_values (self,normalize: bool = True):
        if normalize==True and self.__is_normalized==False:
            self.normalize_coords()
        else: pass
        
        return self.coords.flatten().tolist()
           
class hog_transform(image_preprocessing):
    def __init__(self, image_path, color: str = 'bgr'):
        from skimage.feature import hog
        super().__init__(image_path,color)
        self.image_path = image_path

        # Preprocesamiento
        self.resize_image(64,to_self=True)
        self.segment_image(to_self=True)
        self.to_grayscale(to_self=True)
        
        # Extracción de características con HOG
        self.hog_features, self.hog_image = hog(self.image, orientations=9,pixels_per_cell=(8,8), cells_per_block=(2,2),block_norm='L2-Hys',visualize=True)        
        self.__is_normalized: bool = False
    
    def visualize_gradients(self):
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 10))
        plt.imshow(self.hog_image)
        plt.axis('off')  # Ocultar los ejes
        plt.show()
        
    def normalize_hog(self):
        from skimage import exposure
        self.hog_features = exposure.rescale_intensity(self.hog_features, in_range=(0,10))
        self.__is_normalized: bool = True
        
    def to_csv(self, normalize: bool = True):
        if normalize==True and self.__is_normalized==False:
            self.normalize_hog()
        else: pass
        
        feats = [self.image_path.split('\\')[-2]] + self.hog_features.flatten().tolist()
        columns = ['letra'] + [f'cell_{i}' for i in range(len(feats)-1)]
        df = pd.DataFrame([feats],columns=columns)
        ruta = venv + r'\gradient-processing\processed_data\{}.csv'.format(self.image_path.split("\\")[-3])
        
        df.to_csv(ruta, index=True, mode='a', header=not os.path.exists(ruta))
        
    def extract_values (self,normalize: bool = True):
        if normalize==True and self.__is_normalized==False:
            self.normalize_hog()
        else: pass
        
        self.image = self.hog_image
        return self.hog_features.flatten().tolist()

# Acá iría la clase de CNN

class model_trainer:
    def __init__(self, tecnica: str, modelo: str):
        # keywords = {'técnica': (graph,gradient) , 'modelo':(knn,rf)}
        # Claves
        if tecnica in ['graph','gradient','neural'] and modelo in ['knn','rf','ann']:
            self.representacion = tecnica
            self.clave_modelo = modelo
        else: 
            raise ValueError('Técnica de representación o modelo no identificado.')
        
        self.dataset_path = {'train':os.path.join(venv, f'{self.representacion}-processing\processed_data\Train_Alphabet.csv'),
                             'test':os.path.join(venv, f'{self.representacion}-processing\processed_data\Test_Alphabet.csv')}

        # Conjuntos de entrenamiento y prueba
        train_set = pd.read_csv(self.dataset_path['train'],sep=',', encoding='utf-8',on_bad_lines='skip',usecols=lambda column: column not in ['Unnamed: 0','origen' ,'    '])
        test_set = pd.read_csv(self.dataset_path['test'],sep=',', encoding='utf-8',on_bad_lines='skip',usecols=lambda column: column not in ['Unnamed: 0','origen' ,'    '])

        # Prueba de errores
        lines_train = sum(1 for _ in open(self.dataset_path['train']))
        lines_test = sum(1 for _ in open(self.dataset_path['test']))
        train_corr = train_set.isna().any(axis=1).sum()
        test_corr = test_set.isna().any(axis=1).sum()
        miss_T = train_set.dropna(axis=0).iloc[:,1:].apply(pd.to_numeric, errors='coerce').isna().any(axis=1)
        miss_t = test_set.dropna(axis=0).iloc[:,1:].apply(pd.to_numeric, errors='coerce').isna().any(axis=1)        
        
        if (lines_train > train_set.shape[0] or lines_test > test_set.shape[0] or train_corr>0 or test_corr>0 or miss_T.sum()>0 or miss_t.sum()>0):
            print('----- Sumilla de errores -----\n')
            if (lines_train > train_set.shape[0] or lines_test > test_set.shape[0]):
                print(f'Se han encontrado {lines_train - train_set.shape[0]} errores de lectura en train y {lines_test - test_set.shape[0]} en test. Borrando.')
            if (train_corr>0 or test_corr>0):
                print(f'Se han encontrado {train_corr} filas corruptas en train y {test_corr} en test. Borrando.')
                train_set.dropna(axis=0,inplace=True)
                test_set.dropna(axis=0,inplace=True)
            if (miss_T.sum()>0 or miss_t.sum()>0):
                print(f'Se han encontrado {miss_T.sum()} filas con letras mal posicionadas en train y {miss_t.sum()} en test. Borrando.')
                try:
                    train_set.drop(index=miss_T[miss_T==True].index,inplace=True)
                except: pass
                try:
                    test_set.drop(index=miss_t[miss_t==True].index,inplace=True)
                except: pass
            print('\n------------------------------')
                
        # Almacenamiento de datasets
        X_train, Y_train = train_set.iloc[:,1:].apply(pd.to_numeric, errors='coerce'), train_set.iloc[:,0].apply(lambda x: str(x.decode('utf-8')).strip("b' ") if isinstance(x, bytes) else str(x).strip("b' ")).astype('str').apply(lambda x: x.strip())
        X_test, Y_test = test_set.iloc[:,1:].apply(pd.to_numeric, errors='coerce'), test_set.iloc[:,0].apply(lambda x: str(x.decode('utf-8')).strip("b' ") if isinstance(x, bytes) else str(x).strip("b' ")).astype('str').apply(lambda x: x.strip())
        
        self.train_set = [X_train,Y_train]
        self.test_set = [X_test,Y_test]
        
        # Definición de atributos auxiliares
        self.label = LabelEncoder()
        self.modelo = None
        self.param_distributions = None
        self.__is_trained = False
        self.test_report = None
        self.CM = None
        self.AUC = None
        
    def class_counts(self):  
        train_count = self.train_set[1].value_counts().reset_index()
        train_count.columns = ['Letra', 'En train']
        
        test_count = self.test_set[1].value_counts().reset_index()
        test_count.columns = ['Letra', 'En test']
        
        train_count.Letra = train_count.Letra.astype(str)
        test_count.Letra = test_count.Letra.astype(str)
        
        consolidate = pd.merge(train_count, test_count, on='Letra', how='outer')
        consolidate.fillna(0,inplace=True)
        
        consolidate['En train'] = consolidate['En train'].astype(int)
        consolidate['En test'] = consolidate['En test'].astype(int)
        
        consolidate.sort_values(by='Letra', inplace=True)
        consolidate.reset_index(drop=True, inplace=True)
            
        return consolidate
        
    def __setup_model(self):
        if self.clave_modelo == 'knn':
            self.modelo = KNeighborsClassifier()
            self.param_distributions = {
                'n_neighbors': np.arange(1, 31),
                'weights': ['uniform', 'distance'],
                'metric': ['euclidean', 'manhattan', 'minkowski']
            }
        elif self.clave_modelo == 'rf':
            self.modelo = RandomForestClassifier(random_state=42)
            self.param_distributions = {
                'n_estimators': np.arange(10, 200),
                'max_features': ['auto', 'sqrt', 'log2'],
                'max_depth': [None] + list(np.arange(5, 50, 5)),
                'min_samples_split': np.arange(2, 11),
                'min_samples_leaf': np.arange(1, 11)
            }
        elif self.clave_modelo == 'ann':
            pass
    
    def train_model(self):
        if not self.__is_trained:
            # Configurar el modelo
            self.__setup_model()
            
            X_train = self.train_set[0]
            Y_train = self.label.fit_transform(self.train_set[1])
            
            # Configurar RandomizedSearchCV
            random_search = RandomizedSearchCV(
                estimator=self.modelo,
                param_distributions=self.param_distributions,
                n_iter = 100, # Por ajustar
                cv = 5, # Por ajustar
                verbose = 2,
                random_state=42,
                n_jobs=-1
            )
            
            random_search.fit(X_train,Y_train)
            self.modelo = random_search.best_estimator_
            self.__is_trained = True
        else:
            print('Ya está entrenado el modelo.')
        
    def generate_error_reports(self):
        if not self.__is_trained:
            raise SystemError('No hay modelo entrenado.')
        else:    
            from sklearn.metrics import confusion_matrix, roc_auc_score, roc_curve, auc, classification_report
            from sklearn.preprocessing import label_binarize
            
            # Seteo de variables
            y_test = self.test_set[1]
            y_pred = self.predict(self.test_set[0])
            y_prob = self.modelo.predict_proba(self.test_set[0])
            
            # Reportes generales de error
            self.test_report = classification_report(y_test,y_pred)
            self.CM = pd.DataFrame(confusion_matrix(y_test,y_pred),
                                    index=self.test_set[1].unique(),columns=self.test_set[1].unique())

            # ROC AUC de cada clase
            y_bintest = label_binarize(y_test,
                                       classes=[letra for letra in np.unique(y_test)])
            fpr = dict()
            tpr = dict()
            roc_auc = dict()
            
            for i in range(y_bintest.shape[1]):
                fpr[i], tpr[i], _ = roc_curve(y_bintest[:,i],y_prob[:,i])
                roc_auc[i] = auc(fpr[i],tpr[i])
                
            # ROC AUC: media ponderada
            roc_auc_ovr = roc_auc_score(y_bintest, y_prob, multi_class='ovr')
            
            # ROC AUC: macro
            roc_auc_ovo = roc_auc_score(y_bintest,y_prob,multi_class='ovo')
            
            # Consolidación
            self.AUC = {
                'perclass':roc_auc,
                'ovr':roc_auc_ovr,
                'ovo':roc_auc_ovo
            }
            
    def export_model(self):
        path = os.path.join(venv,f'{self.representacion}-processing/models/{self.clave_modelo}-model.pkl')
        with open(path, 'wb') as file:
            pickle.dump(self,file)
            
    def predict(self, X_test):
        if not self.__is_trained:
            raise ValueError('Modelo no entrenado.')
        else:
            # Como está en Label, la predicción arrojaría un número.
            # Con este nuevo método de reemplazo, te arroja la letra directamente.
            return self.label.inverse_transform(self.modelo.predict(X_test))
        
# En general, este archivo py no debería ser iniciado desde la raíz nunca, dado que es contraproducente. No obstante, lo haré acá para crear los multiprocs.
if __name__ == '__main__':
    create_files('graph')
    create_files('gradient')
    create_files('neural')
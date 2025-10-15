import os
import boto3
from botocore.exceptions import ClientError
from tqdm import tqdm
from config import S3_CONFIG
from datetime import datetime, timedelta, UTC

# Опциональный импорт magic
try:
    import magic
    MAGIC_AVAILABLE = True
except ImportError:
    MAGIC_AVAILABLE = False
    print("Warning: python-magic not available, using fallback MIME detection")

class S3Service:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            endpoint_url=S3_CONFIG['endpoint_url'],
            aws_access_key_id=S3_CONFIG['aws_access_key_id'],
            aws_secret_access_key=S3_CONFIG['aws_secret_access_key'],
            region_name=S3_CONFIG['region_name']
        )
        self.bucket_name = S3_CONFIG['bucket_name']

    def generate_presigned_put_url(self, object_key: str, expires_in: int = 600, content_type: str | None = None, metadata: dict | None = None) -> str | None:
        """
        Генерация presigned URL для PUT (загрузки) объекта в S3 с ограничениями по заголовкам.
        Параметры content_type и metadata должны быть переданы в PUT запросе идентично.
        """
        try:
            params = {
                'Bucket': self.bucket_name,
                'Key': object_key,
            }
            if content_type:
                params['ContentType'] = content_type
            if metadata:
                # Заголовки должны быть переданы как x-amz-meta-*
                params['Metadata'] = metadata
            url = self.s3_client.generate_presigned_url(
                'put_object',
                Params=params,
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            print(f"Ошибка при генерации presigned PUT URL: {e}")
            return None

    def head_object(self, object_key: str) -> dict | None:
        """Возвращает метаданные объекта (HEAD)."""
        try:
            resp = self.s3_client.head_object(Bucket=self.bucket_name, Key=object_key)
            return resp
        except ClientError as e:
            print(f"Ошибка HEAD объекта: {e}")
            return None

    def upload_files(self, file_paths: list, prefix: str = "") -> list:
        """
        Загрузка нескольких файлов в S3
        
        :param file_paths: Список путей к файлам
        :param prefix: Префикс для имен объектов в S3
        :return: Список успешно загруженных файлов
        """
        successful_uploads = []
        for file_path in file_paths:
            if os.path.isfile(file_path):
                object_name = f"{prefix}{os.path.basename(file_path)}"
                try:
                    # Определение MIME-типа файла
                    if MAGIC_AVAILABLE:
                        mime_type = magic.from_file(file_path, mime=True)
                    else:
                        # Fallback: определение по расширению
                        mime_type = self._get_mime_type_by_extension(file_path)
                    
                    # Загрузка файла с отображением прогресса
                    file_size = os.path.getsize(file_path)
                    with tqdm(total=file_size, unit='B', unit_scale=True, desc=f"Загрузка {object_name}") as pbar:
                        self.s3_client.upload_file(
                            file_path,
                            self.bucket_name,
                            object_name,
                            ExtraArgs={'ContentType': mime_type},
                            Callback=lambda bytes_transferred: pbar.update(bytes_transferred)
                        )
                    successful_uploads.append(object_name)
                except ClientError as e:
                    print(f"Ошибка при загрузке файла {file_path}: {e}")
        return successful_uploads

    def upload_files_batch(self, file_paths: list, prefix: str = "", max_workers: int = 10) -> list:
        """
        Массовая загрузка файлов в S3 с использованием ThreadPoolExecutor для параллельной обработки
        
        :param file_paths: Список путей к файлам
        :param prefix: Префикс для имен объектов в S3
        :param max_workers: Максимальное количество потоков для параллельной загрузки
        :return: Список успешно загруженных файлов
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        successful_uploads = []
        failed_uploads = []
        lock = threading.Lock()
        
        def upload_single_file(file_path: str) -> tuple:
            """Загрузка одного файла"""
            if not os.path.isfile(file_path):
                return file_path, False, "Файл не найден"
            
            object_name = f"{prefix}{os.path.basename(file_path)}"
            try:
                # Определение MIME-типа файла
                if MAGIC_AVAILABLE:
                    mime_type = magic.from_file(file_path, mime=True)
                else:
                    # Fallback: определение по расширению
                    mime_type = self._get_mime_type_by_extension(file_path)
                
                # Загрузка файла без прогресс-бара для ускорения
                self.s3_client.upload_file(
                    file_path,
                    self.bucket_name,
                    object_name,
                    ExtraArgs={'ContentType': mime_type}
                )
                return object_name, True, None
            except ClientError as e:
                return file_path, False, str(e)
            except Exception as e:
                return file_path, False, str(e)
        
        # Параллельная загрузка файлов
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Запускаем все задачи
            future_to_file = {executor.submit(upload_single_file, file_path): file_path 
                            for file_path in file_paths}
            
            # Собираем результаты
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    object_name, success, error = future.result()
                    with lock:
                        if success:
                            successful_uploads.append(object_name)
                        else:
                            failed_uploads.append((file_path, error))
                            print(f"Ошибка при загрузке файла {file_path}: {error}")
                except Exception as e:
                    with lock:
                        failed_uploads.append((file_path, str(e)))
                        print(f"Неожиданная ошибка при загрузке файла {file_path}: {e}")
        
        print(f"Массовая загрузка завершена: {len(successful_uploads)} успешно, {len(failed_uploads)} ошибок")
        return successful_uploads

    def download_file(self, object_name: str, file_path: str = None) -> bool:
        """
        Скачивание файла из S3
        
        :param object_name: Имя объекта в S3
        :param file_path: Путь для сохранения файла (если None, будет использовано имя объекта)
        :return: True если скачивание успешно, иначе False
        """
        try:
            if file_path is None:
                file_path = os.path.basename(object_name)
            
            # Создание директории, если она не существует
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Скачивание файла с отображением прогресса
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=object_name)
            total_size = response['ContentLength']
            
            with tqdm(total=total_size, unit='B', unit_scale=True, desc=f"Скачивание {object_name}") as pbar:
                self.s3_client.download_file(
                    self.bucket_name,
                    object_name,
                    file_path,
                    Callback=lambda bytes_transferred: pbar.update(bytes_transferred)
                )
            return True
        except ClientError as e:
            print(f"Ошибка при скачивании файла: {e}")
            return False

    def delete_file(self, object_name: str) -> bool:
        """
        Удаление файла из S3
        
        :param object_name: Имя объекта в S3
        :return: True если удаление успешно, иначе False
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=object_name)
            return True
        except ClientError as e:
            print(f"Ошибка при удалении файла: {e}")
            return False

    def list_files(self, prefix: str = "") -> list:
        """
        Получение списка файлов в S3
        
        :param prefix: Префикс для фильтрации файлов
        :return: Список имен объектов
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )
            return [obj['Key'] for obj in response.get('Contents', [])]
        except ClientError as e:
            print(f"Ошибка при получении списка файлов: {e}")
            return []

    def get_file_url(self, object_name: str, expires_in: int = 604800) -> str:
        """
        Получение временной ссылки на файл
        
        :param object_name: Имя объекта в S3
        :param expires_in: Время жизни ссылки в секундах (по умолчанию 7 дней)
        :return: URL файла
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_name
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            print(f"Ошибка при генерации ссылки: {e}")
            return None

    def get_file_url_with_expiry(self, object_name: str, expires_in: int = 604800) -> tuple:
        """
        Получение временной ссылки на файл с временем истечения
        
        :param object_name: Имя объекта в S3
        :param expires_in: Время жизни ссылки в секундах (по умолчанию 7 дней)
        :return: Кортеж (URL, время истечения)
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_name
                },
                ExpiresIn=expires_in
            )
            expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
            return url, expires_at
        except ClientError as e:
            print(f"Ошибка при генерации ссылки: {e}")
            return None, None

    def is_url_expired(self, expires_at: datetime) -> bool:
        """
        Проверка истечения URL
        
        :param expires_at: Время истечения URL
        :return: True если URL истек, иначе False
        """
        if expires_at is None:
            return True
        return datetime.now(UTC) >= expires_at

    def get_files_url(self, object_names: list, expires_in: int = 604800) -> list:
        """
        Получение временных ссылок на несколько файлов
        
        :param object_names: Список имен объектов в S3
        :param expires_in: Время жизни ссылок в секундах (по умолчанию 7 дней)
        :return: Список URL файлов
        """
        urls = []
        for object_name in object_names:
            url = self.get_file_url(object_name, expires_in)
            if url:
                urls.append(url)
        return urls

    def verify_file_integrity(self, object_key: str, expected_etag: str = None, expected_size: int = None) -> dict:
        """
        Проверка целостности файла в S3
        
        :param object_key: Ключ объекта в S3
        :param expected_etag: Ожидаемый ETag
        :param expected_size: Ожидаемый размер файла
        :return: Словарь с результатами проверки
        """
        try:
            head_response = self.head_object(object_key)
            if not head_response:
                return {'valid': False, 'error': 'Файл не найден'}
            
            actual_etag = head_response.get('ETag', '').strip('"')
            actual_size = head_response.get('ContentLength', 0)
            
            if expected_etag and actual_etag != expected_etag:
                return {
                    'valid': False, 
                    'error': f'ETag не совпадает: ожидался {expected_etag}, получен {actual_etag}'
                }
            
            if expected_size and actual_size != expected_size:
                return {
                    'valid': False,
                    'error': f'Размер не совпадает: ожидался {expected_size}, получен {actual_size}'
                }
            
            return {
                'valid': True,
                'etag': actual_etag,
                'size': actual_size,
                'metadata': head_response.get('Metadata', {})
            }
            
        except Exception as e:
            return {'valid': False, 'error': f'Ошибка проверки: {str(e)}'}

    def delete_files_batch(self, object_keys: list) -> dict:
        """
        Массовое удаление файлов из S3
        
        :param object_keys: Список ключей объектов для удаления
        :return: Словарь с результатами удаления
        """
        try:
            # Группируем ключи по 1000 (лимит S3)
            batch_size = 1000
            deleted_count = 0
            errors = []
            
            for i in range(0, len(object_keys), batch_size):
                batch = object_keys[i:i + batch_size]
                
                # Формируем список объектов для удаления
                objects_to_delete = [{'Key': key} for key in batch]
                
                response = self.s3_client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={
                        'Objects': objects_to_delete,
                        'Quiet': False
                    }
                )
                
                # Подсчитываем успешно удаленные
                deleted_count += len(response.get('Deleted', []))
                
                # Собираем ошибки
                for error in response.get('Errors', []):
                    errors.append({
                        'key': error.get('Key'),
                        'code': error.get('Code'),
                        'message': error.get('Message')
                    })
            
            return {
                'success': True,
                'deleted_count': deleted_count,
                'total_requested': len(object_keys),
                'errors': errors
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'deleted_count': 0,
                'total_requested': len(object_keys)
            }

    def list_objects_with_prefix(self, prefix: str, max_keys: int = 1000) -> list:
        """
        Получение списка объектов с префиксом
        
        :param prefix: Префикс для фильтрации
        :param max_keys: Максимальное количество объектов
        :return: Список объектов
        """
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                MaxKeys=max_keys
            )
            return response.get('Contents', [])
        except Exception as e:
            print(f"Ошибка при получении списка объектов: {e}")
            return []

    def get_object_metadata(self, object_key: str) -> dict:
        """
        Получение метаданных объекта
        
        :param object_key: Ключ объекта
        :return: Словарь с метаданными
        """
        try:
            response = self.s3_client.head_object(Bucket=self.bucket_name, Key=object_key)
            return {
                'etag': response.get('ETag', '').strip('"'),
                'size': response.get('ContentLength', 0),
                'content_type': response.get('ContentType', ''),
                'last_modified': response.get('LastModified'),
                'metadata': response.get('Metadata', {}),
                'storage_class': response.get('StorageClass', 'STANDARD')
            }
        except Exception as e:
            print(f"Ошибка при получении метаданных объекта {object_key}: {e}")
            return {}
    
    def _get_mime_type_by_extension(self, file_path: str) -> str:
        """
        Fallback метод для определения MIME типа по расширению файла
        """
        import mimetypes
        
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            return mime_type
        
        # Дополнительные проверки для изображений
        ext = os.path.splitext(file_path)[1].lower()
        image_types = {
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.gif': 'image/gif',
            '.webp': 'image/webp',
            '.bmp': 'image/bmp',
            '.tiff': 'image/tiff',
            '.svg': 'image/svg+xml'
        }
        
        return image_types.get(ext, 'application/octet-stream') 
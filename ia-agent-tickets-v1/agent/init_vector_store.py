"""
Script para inicializar el vector store con tickets resueltos desde la base de datos SQLite
"""
import sqlite3
import os
from pathlib import Path
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Rutas
DB_PATH = "/home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/backend/src/db/database.sqlite"
VECTOR_STORE_PATH = "/home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent/vector_store"

def load_resolved_tickets_from_db():
    """
    Carga todos los tickets resueltos desde la base de datos SQLite
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Consultar tickets resueltos con sus resoluciones
        cursor.execute("""
            SELECT id, tipo_requerimiento, categoria, descripcion, resolucion 
            FROM tickets 
            WHERE estado = 'resuelto' AND resolucion IS NOT NULL AND resolucion != ''
        """)
        
        tickets = cursor.fetchall()
        conn.close()
        
        logger.info(f"Cargados {len(tickets)} tickets resueltos desde la base de datos")
        
        # Convertir a documentos para el vector store
        documents = []
        for ticket in tickets:
            ticket_id, tipo_requerimiento, categoria, descripcion, resolucion = ticket
            
            # Crear contenido que combine descripción y resolución para búsqueda semántica
            content = f"Problema: {descripcion}\nSolución: {resolucion}"
            
            # Metadatos para filtrado y referencia
            metadata = {
                "ticket_id": ticket_id,
                "tipo_requerimiento": tipo_requerimiento,
                "categoria": categoria,
                "descripcion": descripcion,
                "resolucion": resolucion
            }
            
            doc = Document(page_content=content, metadata=metadata)
            documents.append(doc)
        
        return documents
        
    except Exception as e:
        logger.error(f"Error al cargar tickets desde la base de datos: {e}")
        return []

def initialize_vector_store():
    """
    Inicializa el vector store ChromaDB con los tickets resueltos
    """
    try:
        # Verificar si ya existe el vector store
        if os.path.exists(VECTOR_STORE_PATH):
            logger.info(f"Vector store ya existe en {VECTOR_STORE_PATH}")
            # Cargar el existente
            embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            vector_store = Chroma(
                persist_directory=VECTOR_STORE_PATH,
                embedding_function=embeddings
            )
            return vector_store
        
        # Crear directorio si no existe
        os.makedirs(VECTOR_STORE_PATH, exist_ok=True)
        
        # Cargar tickets resueltos
        documents = load_resolved_tickets_from_db()
        
        if not documents:
            logger.warning("No se encontraron tickets resueltos para cargar")
            # Crear vector store vacío comunque
            embeddings = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            vector_store = Chroma(
                persist_directory=VECTOR_STORE_PATH,
                embedding_function=embeddings
            )
            return vector_store
        
        # Crear embeddings y vector store
        logger.info("Creando embeddings y vector store...")
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        
        vector_store = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            persist_directory=VECTOR_STORE_PATH
        )
        
        # En versiones nuevas de langchain-chroma, el persist es automático al usar persist_directory
        
        logger.info(f"Vector store creado exitosamente con {len(documents)} documentos en {VECTOR_STORE_PATH}")
        return vector_store
        
    except Exception as e:
        logger.error(f"Error al inicializar el vector store: {e}")
        raise e

def add_ticket_to_vector_store(ticket_id, tipo_requerimiento, categoria, descripcion, resolucion):
    """
    Añade un nuevo ticket resuelto al vector store (para aprendizaje en tiempo real)
    """
    try:
        # Cargar vector store existente
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        vector_store = Chroma(
            persist_directory=VECTOR_STORE_PATH,
            embedding_function=embeddings
        )
        
        # Crear documento
        content = f"Problema: {descripcion}\nSolución: {resolucion}"
        metadata = {
            "ticket_id": ticket_id,
            "tipo_requerimiento": tipo_requerimiento,
            "categoria": categoria,
            "descripcion": descripcion,
            "resolucion": resolucion
        }
        
        doc = Document(page_content=content, metadata=metadata)
        
        # Añadir al vector store
        vector_store.add_documents([doc])
        # En versiones nuevas de langchain-chroma, el persist es automático
        
        logger.info(f"Ticket #{ticket_id} añadido al vector store")
        return True
        
    except Exception as e:
        logger.error(f"Error al añadir ticket al vector store: {e}")
        return False

def get_vector_store_from_init():
    """Obtener instancia del vector store desde este módulo"""
    try:
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
        vector_store = Chroma(
            persist_directory=VECTOR_STORE_PATH,
            embedding_function=embeddings
        )
        return vector_store
    except Exception as e:
        logger.error(f"Error al cargar el vector store desde init: {e}")
        return None

if __name__ == "__main__":
    # Inicializar el vector store al ejecutar el script directamente
    vector_store = initialize_vector_store()
    print(f"Vector store inicializado con {vector_store._collection.count()} documentos")
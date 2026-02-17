"""
Database-driven context loading for RAG pipeline.
Replaces documentation ingestion with database queries.
Implements ContextSnapshot and session management for Phase 1.
"""
import sqlite3
import json
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
import uuid
from loguru import logger


@dataclass
class DataSourceConfig:
    """Configuration for a single data source in the RAG pipeline."""
    
    name: str  # 'market_price', 'eia_storage', 'lmp', 'congress_bills', etc.
    tier: int  # 1=critical (always fresh), 2=important (lazy), 3=optional (precomputed)
    freshness_threshold: Optional[timedelta]  # None = fixed schedule (never refresh mid-schedule)
    update_pattern: str  # 'continuous', 'schedule', 'event'
    
    def is_stale(self, snapshot_age: timedelta) -> bool:
        """Check if data is older than freshness threshold."""
        if self.freshness_threshold is None:
            return False  # Fixed schedule, not stale
        return snapshot_age > self.freshness_threshold


# Registry of all data sources with their configuration
# Phase 1: Simple Tier 2 (lazy load) for all sources
DATA_SOURCES_CONFIG: Dict[str, DataSourceConfig] = {
    'market_price': DataSourceConfig(
        name='market_price',
        tier=1,  # Critical - need current price
        freshness_threshold=timedelta(hours=1),
        update_pattern='continuous',
    ),
    'eia_storage': DataSourceConfig(
        name='eia_storage',
        tier=2,  # Important but doesn't change frequently
        freshness_threshold=timedelta(hours=24),
        update_pattern='schedule',
    ),
    'lmp': DataSourceConfig(
        name='lmp',
        tier=2,  # Grid pricing
        freshness_threshold=timedelta(hours=12),
        update_pattern='continuous',
    ),
    'congress_bills': DataSourceConfig(
        name='congress_bills',
        tier=3,  # Optional - policy context
        freshness_threshold=None,  # Event-triggered
        update_pattern='event',
    ),
}


@dataclass
class SourceStatus:
    """Status of a single data source fetch."""
    name: str
    status: str  # 'success', 'cached', 'failure', 'not_stale', 'scheduled'
    value: Optional[Any] = None
    timestamp: Optional[datetime] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'status': self.status,
            'value': self.value,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'error': self.error,
        }


@dataclass
class ContextSnapshot:
    """
    Immutable snapshot of context for a single LLM explanation request.
    Captures all data sources used, their status, and timing information.
    """
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: str = ""
    session_id: str = ""
    
    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    data_as_of: datetime = field(default_factory=datetime.utcnow)
    
    # Data source status
    sources_status: Dict[str, SourceStatus] = field(default_factory=dict)
    
    # Metadata
    tier_1_available: bool = True
    gaps: List[str] = field(default_factory=list)
    confidence_adjustment: float = 1.0
    
    # Output
    explanation_text: Optional[str] = None
    explanation_cached: bool = False
    
    # Signal data snapshot
    signal_data: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'snapshot_id': self.snapshot_id,
            'signal_id': self.signal_id,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat(),
            'data_as_of': self.data_as_of.isoformat(),
            'sources_status': {k: v.to_dict() if isinstance(v, SourceStatus) else v 
                             for k, v in self.sources_status.items()},
            'tier_1_available': self.tier_1_available,
            'gaps': self.gaps,
            'confidence_adjustment': self.confidence_adjustment,
            'explanation_text': self.explanation_text,
            'explanation_cached': self.explanation_cached,
            'signal_data': self.signal_data,
        }
    
    @staticmethod
    def from_dict(data: Dict) -> 'ContextSnapshot':
        """Reconstruct from dictionary (for DB retrieval)."""
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['data_as_of'] = datetime.fromisoformat(data['data_as_of'])
        
        # Reconstruct SourceStatus objects
        sources_status = {}
        for name, status_dict in data.get('sources_status', {}).items():
            if isinstance(status_dict, dict):
                ts = status_dict.get('timestamp')
                if ts:
                    ts = datetime.fromisoformat(ts)
                sources_status[name] = SourceStatus(
                    name=status_dict.get('name', name),
                    status=status_dict.get('status', 'unknown'),
                    value=status_dict.get('value'),
                    timestamp=ts,
                    error=status_dict.get('error'),
                )
            else:
                sources_status[name] = status_dict
        
        data['sources_status'] = sources_status
        return ContextSnapshot(**data)


class DatabaseContextLoader:
    """
    Loads context data from SQLite database for RAG explanations.
    Queries recent data and formats as text documents.
    """
    
    def __init__(self, db_path: str = "data/metis.db"):
        self.db_path = db_path
        self.connection = None
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self.connection is None:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row  # Get rows as dicts
        return self.connection
    
    def close(self):
        """Close database connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def _execute_query(self, query: str, params: Tuple = ()) -> List[Dict]:
        """Execute query and return results as list of dicts."""
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Database query failed: {e}")
            return []
    
    async def get_market_price_recent(self, days: int = 1) -> Tuple[Optional[float], str]:
        """
        Fetch most recent market price.
        
        Returns:
            Tuple of (price, status)
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query = """
                SELECT close as price, date FROM ng_futures_daily
                WHERE date >= ?
                ORDER BY date DESC
                LIMIT 1
            """
            rows = self._execute_query(query, (cutoff_date.isoformat(),))
            
            if rows:
                return rows[0]['price'], 'success'
            else:
                logger.warning(f"No market price found in last {days} days")
                return None, 'not_found'
        except Exception as e:
            logger.error(f"Failed to fetch market price: {e}")
            return None, f'failure: {type(e).__name__}'
    
    async def get_eia_storage_recent(self, days: int = 30) -> Tuple[List[str], str]:
        """
        Fetch recent EIA storage data and format as documents.
        
        Returns:
            Tuple of (formatted_documents, status)
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query = """
                SELECT timestamp, storage_bcf FROM eia_storage
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 30
            """
            rows = self._execute_query(query, (cutoff_date.isoformat(),))
            
            if rows:
                documents = [
                    self._format_eia_document(row) for row in rows
                ]
                return documents, 'success'
            else:
                return [], 'not_found'
        except Exception as e:
            logger.error(f"Failed to fetch EIA storage: {e}")
            return [], f'failure: {type(e).__name__}'
    
    @staticmethod
    def _format_eia_document(row: Dict) -> str:
        """Format EIA storage row as text document."""
        ts = row.get('timestamp', 'unknown')
        storage = row.get('storage_bcf', 'N/A')
        
        return f"""[EIA Storage Snapshot - {ts}]
Working gas: {storage} Bcf
Source: Weekly EIA Natural Gas Storage Report"""
    
    async def get_lmp_recent(self, days: int = 7) -> Tuple[List[str], str]:
        """
        Fetch recent LMP (Locational Marginal Price) data.
        
        Returns:
            Tuple of (formatted_documents, status)
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query = """
                SELECT timestamp, lmp, node_id, iso FROM grid_lmp
                WHERE timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT 50
            """
            rows = self._execute_query(query, (cutoff_date.isoformat(),))
            
            if rows:
                documents = [
                    self._format_lmp_document(row) for row in rows
                ]
                return documents, 'success'
            else:
                return [], 'not_found'
        except Exception as e:
            logger.error(f"Failed to fetch LMP data: {e}")
            return [], f'failure: {type(e).__name__}'
    
    @staticmethod
    def _format_lmp_document(row: Dict) -> str:
        """Format LMP row as text document."""
        ts = row.get('timestamp', 'unknown')
        lmp = row.get('lmp', 'N/A')
        node = row.get('node_id', 'unknown')
        iso = row.get('iso', 'unknown')
        
        return f"""[LMP Price - {ts}]
Node: {node} ({iso})
Locational Marginal Price: ${lmp}/MWh"""
    

    async def get_congress_recent(self, days: int = 180) -> Tuple[List[str], str]:
        """
        Fetch recent congress bills data.
        
        Returns:
            Tuple of (formatted_documents, status)
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            query = """
                SELECT timestamp, congress, bill_type, bill_number, title, latest_action_date, latest_action_text 
                FROM congress_bills
                WHERE timestamp >= ? AND is_energy_related = 1
                ORDER BY timestamp DESC
                LIMIT 20
            """
            rows = self._execute_query(query, (cutoff_date.isoformat(),))
            
            if rows:
                documents = [
                    self._format_congress_document(row) for row in rows
                ]
                return documents, 'success'
            else:
                return [], 'not_found'
        except Exception as e:
            logger.warning(f"Congress bills table error: {e}")
            return [], f'failure: {type(e).__name__}'
    
    @staticmethod
    def _format_congress_document(row: Dict) -> str:
        """Format congress bill row as text document."""
        ts = row.get('timestamp', 'unknown')
        congress = row.get('congress', 'unknown')
        bill_type = row.get('bill_type', 'H.R')
        bill_number = row.get('bill_number', 'unknown')
        title = row.get('title', 'unknown')
        action_date = row.get('latest_action_date', 'unknown')
        action_text = row.get('latest_action_text', 'unknown')
        
        return f"""[Congress {congress} - {bill_type} {bill_number} - {ts}]
{title}
Latest Action ({action_date}): {action_text}"""
    
    async def get_all_context(self, signal_id: str = "", data_as_of: Optional[datetime] = None) -> ContextSnapshot:
        """
        Assemble all available context for explanation.
        
        Args:
            signal_id: Signal identifier
            data_as_of: Cutoff timestamp for data (don't use future data)
        
        Returns:
            ContextSnapshot with all available data
        """
        snapshot = ContextSnapshot(
            signal_id=signal_id,
            data_as_of=data_as_of or datetime.utcnow(),
        )
        
        # Fetch all data sources
        sources_to_fetch = [
            ('market_price', self.get_market_price_recent),
            ('eia_storage', self.get_eia_storage_recent),
            ('lmp', self.get_lmp_recent),
            ('congress_bills', self.get_congress_recent),
        ]
        
        for source_name, fetch_fn in sources_to_fetch:
            try:
                data, status = await fetch_fn()
                snapshot.sources_status[source_name] = SourceStatus(
                    name=source_name,
                    status=status,
                    value=data,
                    timestamp=datetime.utcnow(),
                )
                
                if status != 'success':
                    snapshot.gaps.append(f"{source_name}: {status}")
                    if source_name == 'market_price':
                        snapshot.tier_1_available = False
                
            except Exception as e:
                logger.error(f"Failed to fetch {source_name}: {e}")
                snapshot.sources_status[source_name] = SourceStatus(
                    name=source_name,
                    status=f'failure: {type(e).__name__}',
                    error=str(e),
                )
                snapshot.gaps.append(f"{source_name}: {type(e).__name__}")
        
        # Adjust confidence based on data gaps
        snapshot.confidence_adjustment = self._calculate_confidence_adjustment(snapshot)
        
        return snapshot
    
    async def fetch_with_freshness_check(
        self, 
        source_name: str, 
        cached_snapshot: Optional[ContextSnapshot] = None
    ) -> Tuple[Optional[Any], SourceStatus]:
        """
        Fetch data with tier-aware freshness validation.
        
        Implements tiered failure mode:
        - Tier 1 (critical): Always fresh, warn if unavailable, suggest fallback
        - Tier 2 (important): Lazy load, note limitation if unavailable
        - Tier 3 (optional): Silently omit if unavailable
        
        Args:
            source_name: Name of source to fetch (e.g., 'market_price', 'eia_storage')
            cached_snapshot: Previously cached snapshot to check freshness against
        
        Returns:
            Tuple of (data, SourceStatus) where status indicates fetch outcome
        """
        config = DATA_SOURCES_CONFIG.get(source_name)
        if not config:
            return None, SourceStatus(
                name=source_name,
                status='unknown_source',
                error=f"Source {source_name} not in configuration"
            )
        
        # Check if cached data is still fresh
        if cached_snapshot and source_name in cached_snapshot.sources_status:
            cached_status = cached_snapshot.sources_status[source_name]
            snapshot_age = datetime.utcnow() - cached_snapshot.created_at
            
            if not config.is_stale(snapshot_age):
                logger.debug(f"Using cached {source_name} (age: {snapshot_age.total_seconds():.1f}s)")
                return cached_status.value, SourceStatus(
                    name=source_name,
                    status='cached',
                    value=cached_status.value,
                    timestamp=cached_status.timestamp,
                )
        
        # Fetch fresh data
        try:
            if source_name == 'market_price':
                price, status = await self.get_market_price_recent(days=1)
                if status == 'success':
                    return price, SourceStatus(
                        name=source_name,
                        status='success',
                        value=price,
                        timestamp=datetime.utcnow(),
                    )
                else:
                    # Tier 1: critical - return warning status
                    return None, SourceStatus(
                        name=source_name,
                        status='tier_1_failure',
                        error=f"Market price unavailable: {status}. Recommend using signal's own price.",
                        timestamp=datetime.utcnow(),
                    )
            
            elif source_name == 'eia_storage':
                docs, status = await self.get_eia_storage_recent(days=30)
                if status == 'success':
                    return docs, SourceStatus(
                        name=source_name,
                        status='success',
                        value=docs,
                        timestamp=datetime.utcnow(),
                    )
                else:
                    # Tier 2: important - return limitation status
                    return None, SourceStatus(
                        name=source_name,
                        status='tier_2_unavailable',
                        error=f"EIA storage data unavailable: {status}. Omitting from context.",
                        timestamp=datetime.utcnow(),
                    )
            
            elif source_name == 'lmp':
                docs, status = await self.get_lmp_recent(days=7)
                if status == 'success':
                    return docs, SourceStatus(
                        name=source_name,
                        status='success',
                        value=docs,
                        timestamp=datetime.utcnow(),
                    )
                else:
                    # Tier 2: important - return limitation status
                    return None, SourceStatus(
                        name=source_name,
                        status='tier_2_unavailable',
                        error=f"LMP data unavailable: {status}. Omitting from context.",
                        timestamp=datetime.utcnow(),
                    )
            
            elif source_name == 'congress_bills':
                docs, status = await self.get_congress_recent(days=180)
                if status == 'success':
                    return docs, SourceStatus(
                        name=source_name,
                        status='success',
                        value=docs,
                        timestamp=datetime.utcnow(),
                    )
                else:
                    # Tier 3: optional - silently omit
                    logger.debug(f"Congress bills unavailable ({status}), silently omitting")
                    return None, SourceStatus(
                        name=source_name,
                        status='tier_3_omitted',
                        timestamp=datetime.utcnow(),
                    )
            
            else:
                return None, SourceStatus(
                    name=source_name,
                    status='unsupported_fetch',
                    error=f"No fetch handler for {source_name}"
                )
        
        except Exception as e:
            logger.error(f"Exception during freshness check for {source_name}: {e}")
            return None, SourceStatus(
                name=source_name,
                status='fetch_exception',
                error=f"{type(e).__name__}: {str(e)}",
                timestamp=datetime.utcnow(),
            )
    
    @staticmethod
    def _calculate_confidence_adjustment(snapshot: ContextSnapshot) -> float:
        """Calculate confidence adjustment based on data gaps and tier failures."""
        adjustment = 1.0
        
        if not snapshot.tier_1_available:
            adjustment *= 0.85  # 15% reduction for missing critical data
        
        num_gaps = len(snapshot.gaps)
        gap_penalty = min(num_gaps * 0.05, 0.25)  # Max 25% penalty
        adjustment *= (1.0 - gap_penalty)
        
        return max(adjustment, 0.0)
    
    async def ingest_all_sources(self, scope: str = "startup") -> Dict:
        """
        Ingest all data sources and return as formatted documents (for Rust integration).
        
        Args:
            scope: 'startup' (all data) or 'daily_refresh' (recent only)
        
        Returns:
            Dict with 'documents' list and 'errors' list
        """
        documents = []
        errors = []
        
        try:
            # Get EIA storage documents
            docs, status = await self.get_eia_storage_recent(days=30 if scope == "startup" else 7)
            if docs:
                for i, doc_text in enumerate(docs):
                    documents.append({
                        'id': f"eia_storage_{uuid.uuid4()}",
                        'title': f"EIA Storage Report {i+1}",
                        'content': doc_text,
                        'source': 'EIA',
                        'category': 'supply',
                        'timestamp': datetime.utcnow().isoformat(),
                    })
            else:
                errors.append(f"EIA storage: {status}")
        except Exception as e:
            logger.error(f"EIA storage ingest failed: {e}")
            errors.append(f"EIA storage: {str(e)}")
        
        try:
            # Get LMP documents
            docs, status = await self.get_lmp_recent(days=7 if scope == "startup" else 1)
            if docs:
                for i, doc_text in enumerate(docs):
                    documents.append({
                        'id': f"lmp_{uuid.uuid4()}",
                        'title': f"LMP Pricing Report {i+1}",
                        'content': doc_text,
                        'source': 'CAISO/LMP',
                        'category': 'pricing',
                        'timestamp': datetime.utcnow().isoformat(),
                    })
            else:
                errors.append(f"LMP: {status}")
        except Exception as e:
            logger.error(f"LMP ingest failed: {e}")
            errors.append(f"LMP: {str(e)}")
        
        try:
            # Get Congress documents
            docs, status = await self.get_congress_recent(days=180 if scope == "startup" else 30)
            if docs:
                for i, doc_text in enumerate(docs):
                    documents.append({
                        'id': f"congress_{uuid.uuid4()}",
                        'title': f"Congress Bill Update {i+1}",
                        'content': doc_text,
                        'source': 'Congress',
                        'category': 'policy',
                        'timestamp': datetime.utcnow().isoformat(),
                    })
            else:
                errors.append(f"Congress: {status}")
        except Exception as e:
            logger.error(f"Congress ingest failed: {e}")
            errors.append(f"Congress: {str(e)}")
        
        return {
            'documents': documents,
            'errors': errors,
            'total': len(documents),
        }


class SessionContextManager:
    """
    Manages context snapshots within user sessions.
    Caches explanations to avoid redundant LLM calls.
    """
    
    def __init__(self, db_path: str = "data/metis.db", context_dir: str = "data/rag_context"):
        self.loader = DatabaseContextLoader(db_path)
        self.context_dir = Path(context_dir)
        self.context_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory session cache
        self.session_cache: Dict[Tuple[str, str], ContextSnapshot] = {}
    
    async def get_or_create_snapshot(
        self, 
        signal_id: str, 
        session_id: str,
        force_refresh: bool = False
    ) -> ContextSnapshot:
        """
        Get cached snapshot if available and fresh, otherwise create new one.
        Supports freshness-aware caching and tier-based refresh logic.
        
        Args:
            signal_id: Unique signal identifier
            session_id: User session identifier
            force_refresh: If True, bypass cache and fetch fresh data
        
        Returns:
            ContextSnapshot (cached or newly created, with freshness validation)
        """
        cache_key = (session_id, signal_id)
        cached = None
        
        # Check in-memory cache if not forcing refresh
        if cache_key in self.session_cache and not force_refresh:
            cached = self.session_cache[cache_key]
            snapshot_age = datetime.utcnow() - cached.created_at
            
            # Check if cache is still fresh (at least one Tier 1 refresh interval old)
            if snapshot_age < timedelta(hours=1):
                logger.info(f"Using cached context for signal {signal_id} (age: {snapshot_age.total_seconds():.1f}s)")
                return cached
            else:
                logger.info(f"Cached context expired for signal {signal_id} (age: {snapshot_age.total_seconds():.1f}s), refreshing")
        
        # Create new or refresh snapshot
        logger.info(f"{'Refreshing' if cached else 'Creating'} context snapshot for signal {signal_id} in session {session_id}")
        snapshot = await self.loader.get_all_context(signal_id=signal_id)
        snapshot.session_id = session_id
        
        # Cache it
        self.session_cache[cache_key] = snapshot
        
        # Persist to disk
        self._save_snapshot_to_disk(snapshot)
        
        return snapshot
    
    async def refresh_snapshot_with_checks(
        self,
        existing_snapshot: ContextSnapshot,
        sources_to_update: Optional[list] = None
    ) -> ContextSnapshot:
        """
        Refresh specific sources in an existing snapshot based on freshness.
        
        Useful for selective updates without full re-fetch.
        
        Args:
            existing_snapshot: Previous snapshot to refresh
            sources_to_update: List of sources to refresh (None = all stale sources)
        
        Returns:
            Updated ContextSnapshot
        """
        if sources_to_update is None:
            # Auto-detect stale sources
            sources_to_update = []
            for source_name, config in DATA_SOURCES_CONFIG.items():
                snapshot_age = datetime.utcnow() - existing_snapshot.created_at
                if config.is_stale(snapshot_age):
                    sources_to_update.append(source_name)
            logger.info(f"Auto-detected {len(sources_to_update)} stale sources: {sources_to_update}")
        
        # Refresh detected stale sources
        for source_name in sources_to_update:
            data, status = await self.loader.fetch_with_freshness_check(
                source_name=source_name,
                cached_snapshot=existing_snapshot
            )
            
            existing_snapshot.sources_status[source_name] = status
            
            # Update tier availability
            if source_name == 'market_price' and status.status == 'tier_1_failure':
                existing_snapshot.tier_1_available = False
            
            # Track gaps
            if status.status not in ('success', 'cached', 'not_stale'):
                if source_name not in [g.split(':')[0] for g in existing_snapshot.gaps]:
                    existing_snapshot.gaps.append(f"{source_name}: {status.status}")
        
        # Recalculate confidence
        existing_snapshot.confidence_adjustment = self.loader._calculate_confidence_adjustment(existing_snapshot)
        
        # Update timestamp
        existing_snapshot.data_as_of = datetime.utcnow()
        
        # Persist to disk
        self._save_snapshot_to_disk(existing_snapshot)
        
        return existing_snapshot
    
    def _save_snapshot_to_disk(self, snapshot: ContextSnapshot):
        """Persist snapshot to disk for retrieval later."""
        try:
            snapshot_file = self.context_dir / f"{snapshot.snapshot_id}.json"
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot.to_dict(), f, indent=2, default=str)
            logger.debug(f"Saved context snapshot to {snapshot_file}")
        except Exception as e:
            logger.error(f"Failed to save snapshot to disk: {e}")
    
    def load_snapshot_from_disk(self, snapshot_id: str) -> Optional[ContextSnapshot]:
        """Load previously saved snapshot from disk."""
        try:
            snapshot_file = self.context_dir / f"{snapshot_id}.json"
            if not snapshot_file.exists():
                return None
            
            with open(snapshot_file, 'r') as f:
                data = json.load(f)
            
            return ContextSnapshot.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to load snapshot {snapshot_id}: {e}")
            return None
    
    def clear_session_cache(self, session_id: str):
        """Clear all cached items for a session."""
        keys_to_remove = [k for k in self.session_cache.keys() if k[0] == session_id]
        for key in keys_to_remove:
            del self.session_cache[key]
        logger.info(f"Cleared cache for session {session_id}")
    
    def close(self):
        """Close connections and cleanup."""
        self.loader.close()

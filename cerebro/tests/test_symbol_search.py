import ast
import importlib.util
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]/'app/services'
spec=importlib.util.spec_from_file_location('symbol_catalog',ROOT/'symbol_catalog.py')
catalog=importlib.util.module_from_spec(spec);spec.loader.exec_module(catalog)


class SearchTests(unittest.TestCase):
    def test_shared_load_refresh_backoff_and_stale_catalog(self):
        cache=catalog.SymbolCatalogCache(ttl=10,retry_after=2)
        loader=Mock(return_value=[{'symbol':'US.TEST'}])
        with patch.object(catalog.time,'monotonic',return_value=100):
            first=cache.get('US',loader)
            self.assertEqual(cache.get('US',loader),first)
        self.assertEqual(loader.call_count,1)
        loader.side_effect=RuntimeError('Offline')
        with patch.object(catalog.time,'monotonic',return_value=111):
            self.assertEqual(cache.get('US',loader),first)
            self.assertEqual(cache.get('US',loader),first)
            with self.assertRaises(RuntimeError): cache.get('HK',loader)
            with self.assertRaises(RuntimeError): cache.get('HK',loader)
        self.assertEqual(loader.call_count,3)  # one successful + one stale refresh + one negative load
        loader.side_effect=None;loader.return_value=[{'symbol':'US.NEW'}]
        with patch.object(catalog.time,'monotonic',return_value=114):
            self.assertEqual(cache.get('US',loader),({'symbol':'US.NEW'},))

    def test_concurrent_searches_share_one_catalog_download(self):
        cache=catalog.SymbolCatalogCache();entered=threading.Event();release=threading.Event()
        def load():
            entered.set()
            if not release.wait(timeout=3): raise RuntimeError('Test timed out')
            return [1,2]
        loader=Mock(side_effect=load)
        with ThreadPoolExecutor(max_workers=3) as executor:
            first=executor.submit(cache.get,'US',loader)
            self.assertTrue(entered.wait(timeout=3))
            others=[executor.submit(cache.get,'US',loader) for _ in range(2)]
            release.set()
            for f in [first,*others]: self.assertEqual(f.result(timeout=3),(1,2))
        loader.assert_called_once()

    def test_new_queries_reuse_opend_catalog_and_qualified_symbols(self):
        cls=next(n for n in ast.parse((ROOT/'opend.py').read_text()).body if isinstance(n,ast.ClassDef))
        cls.body=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'_load_symbol_catalog','search_symbols'}]
        ns=dict(RET_OK=0,Market=SimpleNamespace(**{x:x for x in ['US','HK','SH','SZ','SG','MY','JP']}),SecurityType=SimpleNamespace(STOCK='STOCK',ETF='ETF'))
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'opend','exec'),ns)
        client=ns['OpenDClient']();client._symbol_catalog=catalog.SymbolCatalogCache()
        stock=[{'code':'US.VOOG','name':'Growth fund'},{'code':'US.VOO','name':'Broad fund'},{'code':'US.VOOGX','name':'Another growth fund'},{'code':'US.TEST.A','name':'Synthetic class A'}]
        ctx=Mock();ctx.get_stock_basicinfo.return_value=(0,SimpleNamespace(to_dict=lambda kind:stock))
        client._context=lambda:ctx
        first=client.search_symbols('voog',markets=['US'])
        self.assertEqual([r['symbol'] for r in first],['US.VOOG','US.VOOGX'])
        self.assertEqual(client.search_symbols('growth',markets=['US'])[0]['name'],'Growth fund')
        self.assertEqual(client.search_symbols('US.VOOG',markets=['US','HK']),first)
        self.assertEqual(client.search_symbols('US.TEST.A',markets=['US'])[0]['ticker'],'TEST.A')
        self.assertEqual(ctx.get_stock_basicinfo.call_count,2)
        self.assertTrue(all(not any(k.startswith('_') for k in r) for r in first))
        self.assertEqual(client.search_symbols('US.VOOG',markets=['HK']),[])
        self.assertEqual(ctx.close.call_count,2)

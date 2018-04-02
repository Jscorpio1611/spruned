import asyncio
from unittest import TestCase
from unittest.mock import Mock, create_autospec, call

from spruned.daemon.p2p import P2PInterface
from spruned.daemon.tasks.blocks_reactor import BlocksReactor
from spruned.repositories.repository import Repository
from test.utils import async_coro


class TestBlocksReactory(TestCase):
    def setUp(self):
        self.interface = create_autospec(P2PInterface)
        self.repo = create_autospec(Repository)
        self.loopmock = Mock()
        self.delayer = Mock()
        self.sut = BlocksReactor(self.repo, self.interface, self.loopmock, prune=5, delayed_task=self.delayer)
        self.loop = asyncio.get_event_loop()

    def test_check_blockchain_local_behind_remote(self):
        self.sut.set_last_processed_block({'block_hash': 'cafe', 'block_height': 9})
        self.repo.headers.get_best_header.return_value = {'block_hash': 'babe', 'block_height': 10}
        self.interface.get_blocks.return_value = async_coro({'babe': {'block_hash': 'babe', 'block_bytes': b'raw'}})
        self.repo.headers.get_headers_since_height.return_value = [{'block_hash': 'babe', 'block_height': 10}]
        self.repo.blockchain.get_block.return_value = None
        self.repo.blockchain.save_blocks.side_effect = lambda *x: x
        self.loop.run_until_complete(self.sut.check())
        Mock.assert_called_once_with(
            self.repo.blockchain.save_blocks, {'block_hash': 'babe', 'block_bytes': b'raw'}
        )
        self.assertEqual(self.sut._last_processed_block, {'block_hash': 'babe', 'block_height': 10})
        Mock.assert_called_once_with(self.repo.headers.get_best_header)
        Mock.assert_called_once_with(self.interface.get_blocks, 'babe')
        Mock.assert_called_once_with(self.repo.headers.get_headers_since_height, 9, limit=10)
        Mock.assert_called_once_with(self.repo.blockchain.get_block, 'babe', with_transactions=False)
        Mock.assert_called_once_with(self.repo.blockchain.save_blocks, {'block_hash': 'babe', 'block_bytes': b'raw'})

    def test_check_blockchain_local_behind_remote_but_block_already_stored(self):
        self.sut.set_last_processed_block({'block_hash': 'cafe', 'block_height': 9})
        self.repo.headers.get_best_header.return_value = {'block_hash': 'babe', 'block_height': 10}
        self.interface.get_blocks.return_value = async_coro({'babe': {'block_hash': 'babe', 'block_bytes': b'raw'}})
        self.repo.headers.get_headers_since_height.return_value = [{'block_hash': 'babe', 'block_height': 10}]
        self.repo.blockchain.get_block.return_value = {'block_hash': 'babe', 'block_bytes': b'raw'}
        self.repo.blockchain.save_blocks.side_effect = lambda *x: x
        self.loop.run_until_complete(self.sut.check())
        Mock.assert_called_once_with(self.repo.headers.get_best_header)
        Mock.assert_called_once_with(self.repo.headers.get_headers_since_height, 9, limit=10)
        Mock.assert_called_once_with(self.repo.blockchain.get_block, 'babe', with_transactions=False)
        Mock.assert_not_called(self.interface.get_blocks)
        Mock.assert_not_called(self.repo.blockchain.save_blocks)
        self.assertEqual(self.sut._last_processed_block, {'block_hash': 'babe', 'block_height': 10})

    def test_check_blockchain_local_behind_remote_error_saving_block(self):
        self.sut.set_last_processed_block({'block_hash': 'cafe', 'block_height': 9})
        self.repo.headers.get_best_header.return_value = {'block_hash': 'babe', 'block_height': 10}
        self.interface.get_blocks.return_value = async_coro({'babe': {'block_hash': 'babe', 'block_bytes': b'raw'}})
        self.repo.headers.get_headers_since_height.return_value = [{'block_hash': 'babe', 'block_height': 10}]
        self.repo.blockchain.get_block.return_value = None
        self.repo.blockchain.save_blocks.side_effect = ValueError

        self.loop.run_until_complete(self.sut.check())
        Mock.assert_called_once_with(
            self.repo.blockchain.save_blocks, {'block_hash': 'babe', 'block_bytes': b'raw'}
        )
        Mock.assert_called_once_with(self.repo.headers.get_best_header)
        Mock.assert_called_once_with(self.interface.get_blocks, 'babe')
        Mock.assert_called_once_with(self.repo.headers.get_headers_since_height, 9, limit=10)
        Mock.assert_called_once_with(self.repo.blockchain.get_block, 'babe', with_transactions=False)
        self.assertEqual(self.sut._last_processed_block, {'block_hash': 'cafe', 'block_height': 9})

    def test_check_blockchain_local_a_lot_behind(self):
        """
        something bad happened around block 16, we saved it, we didn't tracked it and we start over 5 blocks later.
        also, the last block tracked by the blockheader reactor was stuck ad block 9.
        basically, everything is screwed up, but we recover and download the needed blocks.
        """
        self.sut.set_last_processed_block({'block_hash': 'cafe', 'block_height': 9})
        self.repo.headers.get_best_header.return_value = {'block_hash': 'babe', 'block_height': 20}
        self.interface.get_blocks.return_value = async_coro(
            {
                'block17': {'block_hash': 'block17', 'block_bytes': b'raw'},
                'block18': {'block_hash': 'block18', 'block_bytes': b'raw'},
                'block19': {'block_hash': 'block19', 'block_bytes': b'raw'},
                'block20': {'block_hash': 'block20', 'block_bytes': b'raw'}
            }
        )
        self.repo.headers.get_headers_since_height.return_value = [
            {'block_hash': 'block16', 'block_height': 16},
            {'block_hash': 'block17', 'block_height': 17},
            {'block_hash': 'block18', 'block_height': 18},
            {'block_hash': 'block19', 'block_height': 19},
            {'block_hash': 'block20', 'block_height': 20}
        ]
        self.repo.blockchain.get_block.side_effect = [
            {'block_hash': 'block16', 'block_bytes': b'raw'}, None, None, None, None
        ]
        self.repo.blockchain.save_blocks.side_effect = [
            {'block_hash': 'block17', 'block_bytes': b'raw'},
            {'block_hash': 'block18', 'block_bytes': b'raw'},
            {'block_hash': 'block19', 'block_bytes': b'raw'},
            {'block_hash': 'block20', 'block_bytes': b'raw'}
        ]
        self.repo.blockchain.save_blocks.side_effect = lambda *x: x

        self.loop.run_until_complete(self.sut.check())

        Mock.assert_called_once_with(self.repo.headers.get_best_header)
        Mock.assert_called_once_with(self.repo.headers.get_headers_since_height, 15, limit=10)
        Mock.assert_has_calls(
            self.repo.blockchain.get_block,
            calls=[
                call('block16', with_transactions=False),
                call('block17', with_transactions=False),
                call('block18', with_transactions=False),
                call('block19', with_transactions=False),
                call('block20', with_transactions=False)
            ]
        )
        Mock.assert_called_once_with(self.interface.get_blocks, 'block17', 'block18', 'block19', 'block20')
        self.assertEqual(self.sut._last_processed_block, {'block_hash': 'block20', 'block_height': 20})

        Mock.assert_called_once_with(
            self.repo.blockchain.save_blocks,
            {'block_hash': 'block17', 'block_bytes': b'raw'},
            {'block_hash': 'block18', 'block_bytes': b'raw'},
            {'block_hash': 'block19', 'block_bytes': b'raw'},
            {'block_hash': 'block20', 'block_bytes': b'raw'}
        )
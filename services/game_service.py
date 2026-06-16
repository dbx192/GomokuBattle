from typing import List, Tuple, Optional

class GomokuGame:
    BOARD_SIZE = 15
    EMPTY = 0
    BLACK = 1
    WHITE = 2
    
    def __init__(self):
        self.board = [[self.EMPTY] * self.BOARD_SIZE for _ in range(self.BOARD_SIZE)]
        self.moves = []
        self.current_player = self.BLACK
    
    def add_move(self, row: int, col: int, player: int) -> bool:
        if self.board[row][col] != self.EMPTY:
            return False
        self.board[row][col] = player
        self.moves.append((row, col, player))
        # 落子后切换当前玩家
        self.current_player = self.WHITE if player == self.BLACK else self.BLACK
        return True
    
    def undo_move(self) -> Optional[Tuple[int, int, int]]:
        if not self.moves:
            return None
        row, col, player = self.moves.pop()
        self.board[row][col] = self.EMPTY
        self.current_player = self.BLACK if len(self.moves) % 2 == 0 else self.WHITE
        return row, col, player
    
    def check_winner(self) -> Tuple[Optional[int], Optional[List[List[int]]]]:
        directions = [
            [(0, 1), (0, -1)],
            [(1, 0), (-1, 0)],
            [(1, 1), (-1, -1)],
            [(1, -1), (-1, 1)]
        ]
        
        for row in range(self.BOARD_SIZE):
            for col in range(self.BOARD_SIZE):
                if self.board[row][col] == self.EMPTY:
                    continue
                
                player = self.board[row][col]
                for d1, d2 in directions:
                    line = [[row, col]]
                    
                    r, c = row + d1[0], col + d1[1]
                    while 0 <= r < self.BOARD_SIZE and 0 <= c < self.BOARD_SIZE and self.board[r][c] == player:
                        line.append([r, c])
                        r += d1[0]
                        c += d1[1]
                    
                    r, c = row + d2[0], col + d2[1]
                    while 0 <= r < self.BOARD_SIZE and 0 <= c < self.BOARD_SIZE and self.board[r][c] == player:
                        line.insert(0, [r, c])
                        r += d2[0]
                        c += d2[1]
                    
                    if len(line) >= 5:
                        return player, line[:5]
        
        return None, None
    
    def get_ai_move(self) -> Tuple[int, int]:
        best_score = -float('inf')
        best_move = (self.BOARD_SIZE // 2, self.BOARD_SIZE // 2)
        
        for row in range(self.BOARD_SIZE):
            for col in range(self.BOARD_SIZE):
                if self.board[row][col] == self.EMPTY:
                    score = self.evaluate_position(row, col, self.WHITE)
                    score += self.evaluate_position(row, col, self.BLACK) * 0.9
                    
                    if score > best_score:
                        best_score = score
                        best_move = (row, col)
        
        return best_move
    
    def evaluate_position(self, row: int, col: int, player: int) -> int:
        score = 0
        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
        
        for dr, dc in directions:
            count = 1
            open_ends = 0
            
            for i in range(1, 5):
                r, c = row + dr * i, col + dc * i
                if 0 <= r < self.BOARD_SIZE and 0 <= c < self.BOARD_SIZE:
                    if self.board[r][c] == player:
                        count += 1
                    elif self.board[r][c] == self.EMPTY:
                        open_ends += 1
                        break
                    else:
                        break
                else:
                    break
            
            for i in range(1, 5):
                r, c = row - dr * i, col - dc * i
                if 0 <= r < self.BOARD_SIZE and 0 <= c < self.BOARD_SIZE:
                    if self.board[r][c] == player:
                        count += 1
                    elif self.board[r][c] == self.EMPTY:
                        open_ends += 1
                        break
                    else:
                        break
                else:
                    break
            
            if count >= 5:
                score += 100000
            elif count == 4:
                score += 10000 if open_ends == 2 else 1000
            elif count == 3:
                score += 100 if open_ends == 2 else 10
            elif count == 2:
                score += 1 if open_ends == 2 else 0
        
        if self.moves:
            for move in self.moves:
                dist = abs(row - move[0]) + abs(col - move[1])
                if dist <= 2:
                    score += 5 - dist
        
        return score
    
    def to_dict(self) -> dict:
        return {
            "board": self.board,
            "moves": self.moves,
            "current_player": self.current_player
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "GomokuGame":
        game = cls()
        game.board = data.get("board", [[cls.EMPTY] * cls.BOARD_SIZE for _ in range(cls.BOARD_SIZE)])
        game.moves = data.get("moves", [])
        game.current_player = data.get("current_player", cls.BLACK)
        return game

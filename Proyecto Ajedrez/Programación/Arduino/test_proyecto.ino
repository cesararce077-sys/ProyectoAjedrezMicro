#include <Adafruit_NeoPixel.h>

#define DATA_PIN 6
#define W 8
#define H 8
#define NUM_LEDS (W * H)

Adafruit_NeoPixel strip(NUM_LEDS, DATA_PIN, NEO_GRB + NEO_KHZ800);

// --- Piece encoding ---
enum Piece : uint8_t {
  EMPTY = 0,
  WP, WN, WB, WR, WQ, WK,
  BP, BN, BB, BR, BQ, BK
};

// Board stored as [rank][file] where rank 0 = rank 1 (A1..H1)
Piece board[8][8];

// Optional overlay for legal moves
bool legalMove[8][8];

// --- Colors (adjust to taste) ---
// Using strip.Color(R,G,B)
uint32_t COLORS[13]; // index by Piece (0..12), EMPTY uses 0

// highlight color for legal moves (separate)
uint32_t HIGHLIGHT_COLOR;

uint16_t XY_to_index(uint8_t file, uint8_t rank) {
  // file: 0..7 maps A..H
  // rank: 0..7 maps 1..8
  // serpentine rows along rank
  if (rank % 2 == 0) {
    // rank 1,3,5,7 : A->H
    return rank * 8 + file;
  } else {
    // rank 2,4,6,8 : H->A
    return rank * 8 + (7 - file);
  }
}

void initColors() {
  // EMPTY
  COLORS[EMPTY] = strip.Color(0, 0, 0);

  // White pieces (cooler / brighter shades)
  COLORS[WP] = strip.Color(40, 40, 40);
  COLORS[WN] = strip.Color(0, 80, 120);
  COLORS[WB] = strip.Color(0, 120, 60);
  COLORS[WR] = strip.Color(120, 80, 0);
  COLORS[WQ] = strip.Color(140, 0, 140);
  COLORS[WK] = strip.Color(160, 160, 0);

  // Black pieces (darker / warmer shades)
  COLORS[BP] = strip.Color(10, 10, 10);
  COLORS[BN] = strip.Color(0, 30, 60);
  COLORS[BB] = strip.Color(0, 50, 20);
  COLORS[BR] = strip.Color(60, 30, 0);
  COLORS[BQ] = strip.Color(70, 0, 70);
  COLORS[BK] = strip.Color(80, 80, 0);

  // Legal move highlight (cyan-ish)
  HIGHLIGHT_COLOR = strip.Color(0, 120, 120);
}

// Clear the board + legal overlay
void clearState() {
  for (uint8_t r = 0; r < 8; r++) {
    for (uint8_t f = 0; f < 8; f++) {
      board[r][f] = EMPTY;
      legalMove[r][f] = false;
    }
  }
}

Piece fenCharToPiece(char c) {
  switch (c) {
    case 'P': return WP;
    case 'N': return WN;
    case 'B': return WB;
    case 'R': return WR;
    case 'Q': return WQ;
    case 'K': return WK;
    case 'p': return BP;
    case 'n': return BN;
    case 'b': return BB;
    case 'r': return BR;
    case 'q': return BQ;
    case 'k': return BK;
    default:  return EMPTY;
  }
}

// Parse only the placement field of FEN (first part before space)
// Example: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
bool loadBoardFromFEN(const String &fen) {
  clearState();

  int space = fen.indexOf(' ');
  String placement = (space == -1) ? fen : fen.substring(0, space);

  // FEN ranks go 8 down to 1. We'll map to rank index 7..0.
  uint8_t fenRank = 8;
  uint8_t file = 0;

  for (uint16_t i = 0; i < placement.length(); i++) {
    char c = placement[i];

    if (c == '/') {
      if (file != 8) return false; // each rank must have 8 files filled
      fenRank--;
      if (fenRank == 0) return false;
      file = 0;
      continue;
    }

    if (c >= '1' && c <= '8') {
      uint8_t empties = c - '0';
      file += empties;
      if (file > 8) return false;
      continue;
    }

    Piece p = fenCharToPiece(c);
    if (p == EMPTY) return false;

    if (file >= 8) return false;

    // Convert fenRank (8..1) to our rank index (7..0)
    uint8_t rankIndex = fenRank - 1; // 8->7, 1->0
    board[rankIndex][file] = p;
    file++;
  }

  // After parsing, we should have filled rank 1 and file==8
  if (fenRank != 1 || file != 8) return false;

  return true;
}

// Render board to LEDs, with optional legal move overlay
void render() {
  for (uint8_t rank = 0; rank < 8; rank++) {
    for (uint8_t file = 0; file < 8; file++) {
      uint16_t idx = XY_to_index(file, rank);

      uint32_t base = COLORS[board[rank][file]];
      if (legalMove[rank][file]) {
        // Overlay: you can either replace or blend.
        // Replace is clearer:
        strip.setPixelColor(idx, HIGHLIGHT_COLOR);
      } else {
        strip.setPixelColor(idx, base);
      }
    }
  }
  strip.show();
}

// Example: set some legal moves for testing (you will replace this later)
void demoLegalMoves() {
  for (uint8_t r = 0; r < 8; r++)
    for (uint8_t f = 0; f < 8; f++)
      legalMove[r][f] = false;

  // Highlight E4, E5, E6 (file=4, ranks=3..5)
  legalMove[3][4] = true;
  legalMove[4][4] = true;
  legalMove[5][4] = true;
}

String readLineFromSerial() {
  static String line = "";
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      String out = line;
      line = "";
      out.trim();
      return out;
    } else {
      line += c;
      if (line.length() > 200) { // safety
        line = "";
        return "";
      }
    }
  }
  return "";
}

void setup() {
  Serial.begin(115200);
  strip.begin();
  strip.setBrightness(80); // keep power reasonable (0..255)
  initColors();
  clearState();
  render();

  Serial.println("Send FEN (full FEN or just placement).");
}

void loop() {
  String fen = readLineFromSerial();
  if (fen.length() > 0) {
    if (loadBoardFromFEN(fen)) {
      // demoLegalMoves(); // uncomment to test highlighting
      render();
      Serial.println("OK");
    } else {
      Serial.println("ERR: bad FEN");
    }
  }
}


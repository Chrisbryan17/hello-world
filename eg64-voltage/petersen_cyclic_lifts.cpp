// Exact cyclic-voltage lift census over the Petersen graph.
//
// For a connected base graph, vertex switching sets all spanning-tree
// voltages to zero without changing the isomorphism class of the derived
// cyclic cover. Petersen has cycle rank six, so each modulus q leaves exactly
// q^6 gauge-normalized assignments. A job fixes the first chord voltage and
// exhausts the remaining q^5 assignments.
#include <array>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <utility>
#include <vector>

using namespace std;

class PetersenLiftSearch {
 public:
  PetersenLiftSearch(int modulus, int fixed_first)
      : q_(modulus), fixed_first_(fixed_first), order_(10 * modulus),
        neighbours_(order_), degree_(order_), used_(order_) {
    edges_ = {{0, 1}, {0, 4}, {0, 5}, {1, 2}, {1, 6},
              {2, 3}, {2, 7}, {3, 4}, {3, 8}, {4, 9},
              {5, 7}, {5, 8}, {6, 8}, {6, 9}, {7, 9}};
    // Complement of the deterministic BFS spanning tree rooted at vertex 0.
    chords_ = {{2, 3}, {2, 7}, {3, 8}, {6, 8}, {6, 9}, {7, 9}};
    voltages_[0] = fixed_first_;
  }

  void Run() { Enumerate(1); }

  int ExitCode() const { return found_ ? 10 : 0; }

  void PrintJson(double seconds) const {
    cout << "{\"modulus\":" << q_
         << ",\"fixed_first\":" << fixed_first_
         << ",\"assignments_checked\":" << checked_
         << ",\"counts\":{"
         << "\"4\":" << counts_[0] << ','
         << "\"8\":" << counts_[1] << ','
         << "\"16\":" << counts_[2] << ','
         << "\"32\":" << counts_[3] << ','
         << "\"64\":" << counts_[4] << ','
         << "\"128\":" << counts_[5] << ','
         << "\"none\":" << counts_[6] << "},"
         << "\"seconds\":" << seconds << ",\"witness\":";
    if (found_) {
      cout << '[';
      for (int index = 0; index < 6; ++index) {
        if (index) cout << ',';
        cout << witness_[index];
      }
      cout << ']';
    } else {
      cout << "null";
    }
    cout << "}\n";
  }

 private:
  int q_;
  int fixed_first_;
  int order_;
  vector<pair<int, int>> edges_;
  vector<pair<int, int>> chords_;
  vector<array<int, 3>> neighbours_;
  vector<int> degree_;
  vector<unsigned char> used_;
  array<int, 6> voltages_{};
  array<int, 6> witness_{};
  uint64_t checked_ = 0;
  array<uint64_t, 7> counts_{};
  bool found_ = false;

  int ChordIndex(pair<int, int> edge) const {
    for (int index = 0; index < 6; ++index) {
      if (chords_[index] == edge) return index;
    }
    return -1;
  }

  void AddEdge(int first, int second) {
    neighbours_[first][degree_[first]++] = second;
    neighbours_[second][degree_[second]++] = first;
  }

  void BuildLift() {
    fill(degree_.begin(), degree_.end(), 0);
    for (const auto edge : edges_) {
      const int chord_index = ChordIndex(edge);
      const int voltage = chord_index < 0 ? 0 : voltages_[chord_index];
      for (int fibre = 0; fibre < q_; ++fibre) {
        const int first = edge.first * q_ + fibre;
        const int second = edge.second * q_ + ((fibre + voltage) % q_);
        AddEdge(first, second);
      }
    }
    for (const int degree : degree_) {
      if (degree != 3) {
        cerr << "derived lift is not cubic\n";
        exit(3);
      }
    }
  }

  bool Adjacent(int first, int second) const {
    return neighbours_[first][0] == second ||
           neighbours_[first][1] == second ||
           neighbours_[first][2] == second;
  }

  bool CycleDfs(int start, int first, int current, int depth, int length) {
    if (depth == length) {
      return Adjacent(current, start) && first < current;
    }
    for (int slot = 0; slot < 3; ++slot) {
      const int next = neighbours_[current][slot];
      if (next <= start || used_[next]) continue;
      if (depth == length - 1 && !Adjacent(next, start)) continue;
      used_[next] = 1;
      if (CycleDfs(start, first, next, depth + 1, length)) {
        used_[next] = 0;
        return true;
      }
      used_[next] = 0;
    }
    return false;
  }

  bool HasCycle(int length) {
    if (length > order_) return false;
    fill(used_.begin(), used_.end(), 0);
    for (int start = 0; start < order_; ++start) {
      used_[start] = 1;
      for (int slot = 0; slot < 3; ++slot) {
        const int first = neighbours_[start][slot];
        if (first <= start) continue;
        used_[first] = 1;
        if (CycleDfs(start, first, first, 2, length)) {
          used_[first] = 0;
          used_[start] = 0;
          return true;
        }
        used_[first] = 0;
      }
      used_[start] = 0;
    }
    return false;
  }

  int Classify() {
    BuildLift();
    static constexpr array<int, 6> lengths = {4, 8, 16, 32, 64, 128};
    for (int index = 0; index < static_cast<int>(lengths.size()); ++index) {
      if (lengths[index] <= order_ && HasCycle(lengths[index])) return index;
    }
    return 6;
  }

  void Enumerate(int position) {
    if (found_) return;
    if (position == 6) {
      const int classification = Classify();
      ++checked_;
      ++counts_[classification];
      if (classification == 6) {
        found_ = true;
        witness_ = voltages_;
      }
      return;
    }
    for (int value = 0; value < q_; ++value) {
      voltages_[position] = value;
      Enumerate(position + 1);
      if (found_) return;
    }
  }
};

int main(int argc, char** argv) {
  if (argc != 3) {
    cerr << "usage: petersen_cyclic_lifts MODULUS FIXED_FIRST_VOLTAGE\n";
    return 2;
  }
  const int modulus = stoi(argv[1]);
  const int fixed_first = stoi(argv[2]);
  if (modulus < 2 || fixed_first < 0 || fixed_first >= modulus) {
    cerr << "invalid modulus or fixed voltage\n";
    return 2;
  }
  const auto start = chrono::steady_clock::now();
  PetersenLiftSearch search(modulus, fixed_first);
  search.Run();
  const double seconds = chrono::duration<double>(
      chrono::steady_clock::now() - start).count();
  search.PrintJson(seconds);
  return search.ExitCode();
}

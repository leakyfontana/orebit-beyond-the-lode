using System.Collections;
using System.Collections.Generic;
using UnityEngine.Tilemaps;
using UnityEngine;

public class PlayerCollisions : MonoBehaviour
{
	public BoxCollider2D bottom_detector;
	public BoxCollider2D front_detector;
	public GameObject block_detector_bottom;
	public GameObject block_detector_side;
	
	public (int x, int y) getBlockPositionBottomPlayer(){
		Vector3 position = block_detector_bottom.transform.position;
		int x = Mathf.FloorToInt(position.x);
		int y = Mathf.Abs(Mathf.FloorToInt(position.y));
		return (x, y);
	}
	
	public (int x, int y) getBlockPositionSidePlayer(){
		Vector3 position = block_detector_side.transform.position;
		int x = Mathf.FloorToInt(position.x);
		int y = Mathf.Abs(Mathf.FloorToInt(position.y));
		return (x, y);
	}
}
